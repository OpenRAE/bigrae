"""Generic single-use VM admission through the incumbent native range lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from shared.authorization import AuthorizationRequest, TargetRef
from shared.authorization.policy import require_authorization
from shared.credentials import (
    CredentialContext,
    resolve_credential_scope,
    resolve_current_credential,
    resolve_local_credential,
)
from shared.disposable_workers import (
    DEFAULT_PROFILE,
    WorkerHostProfile,
    WorkerPolicy,
    WorkerProfileBinding,
    WorkerProfileError,
)
from shared.identity_scope import ResourceScope
from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose, evaluate_gcp_backend_admission

if TYPE_CHECKING:
    from engine.models import CapacityReservation, DisposableWorker
    from shared.capacity import MetricVerdict, PartitionRef

    from ._principal_range_create import PreparedRaesRangeCreation


@dataclass(frozen=True, slots=True)
class WorkerView:
    """Non-secret lifecycle facts; native status remains the authoritative state."""

    worker_id: UUID
    experiment_id: UUID
    trial_id: UUID | None
    status: str
    deadline: datetime
    retired: bool
    held: bool
    recovery_required: bool
    qualified: bool
    recovery_reason: str
    recovery_attempts: int
    next_recovery_at: datetime
    retiring: bool = False


def _installation_authority(credential: CredentialContext) -> CredentialContext:
    """Require current installation cloud-management authority."""
    current = resolve_current_credential(credential)
    require_authorization(
        AuthorizationRequest(
            current.principal,
            "installation.manage_cloud_authority",
            TargetRef("installation"),
            ResourceScope("installation"),
            current.ceiling,
        )
    )
    return current


def configure_worker_policy(credential: CredentialContext, configuration: object) -> None:
    """Publish operator maxima and apparatus, independently of caller launches."""
    from engine.models import WorkerPolicyRecord

    current = _installation_authority(credential)
    try:
        policy = WorkerPolicy.model_validate(configuration)
    except ValueError:
        raise ValueError("Worker policy is invalid") from None
    with transaction.atomic():
        if resolve_local_credential(current) != current:
            raise ValueError("Worker policy authority changed")
        record, _ = WorkerPolicyRecord.objects.get_or_create(
            pk=1, defaults={"configuration": policy.model_dump(mode="json")}
        )
        record = WorkerPolicyRecord.objects.select_for_update().get(pk=record.pk)
        record.configuration = policy.model_dump(mode="json")
        record.save(update_fields=["configuration", "updated_at"])
        _audit(current, None, "worker_policy")


def _worker_backend() -> BackendAdmission:
    """Refuse a deployment without an admitted GCE live-fire backend."""
    import os

    admission = evaluate_gcp_backend_admission(
        os.environ.get("GCP_RANGE_BACKEND"), os.environ.get("GCP_RANGE_PLANE"), InstantiationPurpose.LIVE_FIRE
    )
    if settings.CLOUD_PROVIDER != "gcp" or not admission.admitted or admission.backend != "gce":
        raise ValueError("Worker backend is unsupported")
    return admission


def create_disposable_worker(
    credential: CredentialContext,
    *,
    scope: ResourceScope,
    worker_id: UUID,
    experiment_id: UUID,
    trial_id: UUID | None = None,
    profile_binding: WorkerProfileBinding | None = None,
) -> WorkerView:
    """Atomically reserve global limits, capacity and native durable dispatch.

    A new worker uses the exact ``profile_binding`` that its batch retains, or the default profile.
    """
    from engine.models import DisposableWorker, Range, WorkerPolicyRecord
    from management.services import human_principal_user_id
    from workspaces.services import resolve_range_scope_binding

    from ._principal_range_create import prepare_raes_range_creation
    from ._raes_range import RangeBindings, create_raes_range

    _validate_worker_custody(scope, worker_id, experiment_id, trial_id)
    current = resolve_current_credential(credential)
    resolved = resolve_range_scope_binding(scope, member=current.principal)
    user_id = human_principal_user_id(current.principal) if current.principal.kind == "human" else None
    existing = DisposableWorker.objects.select_related("range").filter(pk=worker_id).first()
    if existing is not None:
        _validate_replay(existing, scope, experiment_id, trial_id, current.principal.uuid)
        from engine.models import ProvisionerLaunchIntent
        from shared.authorization.policy import scope_parent

        parent = scope_parent(scope)
        require_authorization(
            AuthorizationRequest(current.principal, f"{parent.type}.launch_range", parent, scope, current.ceiling)
        )
        if ProvisionerLaunchIntent.objects.filter(
            authority_resource_uuid=worker_id, payload__operation="provision"
        ).exists():
            return _view(existing)
    admission = _worker_backend()
    record = WorkerPolicyRecord.objects.get(pk=1)
    policy = WorkerPolicy.model_validate(record.configuration)
    profile = _admitted_profile(existing, policy, profile_binding)
    bindings = RangeBindings(credential=current, resource_scope=scope, cms_range_uuid=worker_id, defer_dispatch=True)
    prepared = prepare_raes_range_creation(bindings, resolved.workspace_id, user_id, profile.plan)
    bindings = replace(bindings, prepared_creation=prepared)
    now = timezone.now()
    with transaction.atomic():
        locked_scope = resolve_range_scope_binding(scope, member=current.principal, for_update=True)
        if locked_scope != resolved:
            raise ValueError("Worker scope changed")
        record = WorkerPolicyRecord.objects.select_for_update().get(pk=1)
        if record.configuration != policy.model_dump(mode="json"):
            raise ValueError("Worker policy changed")
        existing = DisposableWorker.objects.select_related("range").filter(pk=worker_id).first()
        if existing is not None:
            _validate_replay(existing, scope, experiment_id, trial_id, current.principal.uuid)
            if existing.profile_digest != profile.digest:
                raise ValueError("Worker replay conflicts")
        else:
            _check_worker_limits(policy)
            _reserve_capacity(profile, worker_id, now)
            request_id = uuid4()
            created = create_raes_range(
                request_id=request_id,
                user_id=user_id,
                compiled_plan=profile.plan,
                workspace_id=resolved.workspace_id,
                egress_mode=profile.egress_mode,
                backend_admission=admission,
                bindings=bindings,
            )
            runtime = Range.objects.get(uuid=created.range_id)
            worker = DisposableWorker.objects.create(
                id=worker_id,
                range=runtime,
                request_id=request_id,
                experiment_id=experiment_id,
                initial_trial_id=trial_id,
                trial_id=trial_id,
                profile=profile.model_dump(mode="json"),
                profile_digest=profile.digest,
                capacity_scope_ref=profile.capacity_scope_ref,
                deadline=now + timedelta(seconds=policy.lifetime_seconds),
                max_recovery_attempts=policy.recovery_attempts,
                hold_review_seconds=policy.hold_review_seconds,
                next_recovery_at=now + timedelta(seconds=policy.lifetime_seconds),
            )
            from ._worker_software import pin_worker_software

            _validate_created_worker(worker, profile, scope)
            pin_worker_software(profile, runtime, scope)
            _audit(current, worker, "worker_create")
    return _dispatch_worker(current, scope, worker_id, prepared)


def _validate_replay(
    worker: DisposableWorker, scope: ResourceScope, experiment: UUID, trial: UUID | None, owner: UUID
) -> None:
    """A replay recovers the same immutable custody, not a new apparatus choice."""
    if worker_credential_scope(worker.pk) != scope or (
        worker.experiment_id,
        worker.initial_trial_id,
        worker.range.owner_principal_uuid,
    ) != (experiment, trial, owner):
        raise ValueError("Worker replay conflicts")


def _dispatch_worker(
    current: CredentialContext, scope: ResourceScope, worker_id: UUID, prepared: PreparedRaesRangeCreation
) -> WorkerView:
    """Publish custody and dispatch retained inputs under the admission lock order."""
    from engine.models import ProvisionerLaunchIntent, WorkerPolicyRecord
    from workspaces.services import resolve_range_scope_binding

    from ._raes_range import dispatch_created_raes_range
    from ._worker_relationships import publish_worker_relationships
    from ._worker_retirement import _lock_worker

    publish_worker_relationships(worker_id)
    with transaction.atomic():
        resolve_range_scope_binding(scope, member=current.principal, for_update=True)
        WorkerPolicyRecord.objects.select_for_update().get(pk=1)
        worker = _lock_worker(worker_id)
        if worker.retirement_at is not None or worker.terminal_at is not None:
            raise ValueError("Worker retirement already admitted")
        if not ProvisionerLaunchIntent.objects.filter(
            authority_resource_uuid=worker.pk, payload__operation="provision"
        ).exists():
            dispatch_created_raes_range(worker.request_id, credential=current, prepared_creation=prepared)
    return _view(worker)


def _validate_worker_custody(scope: ResourceScope, worker_id: UUID, experiment_id: UUID, trial_id: UUID | None) -> None:
    """Validate nonzero caller custody and explicit customer scope."""
    if (
        scope.kind != "account"
        or any(not isinstance(value, UUID) or not value.int for value in (worker_id, experiment_id))
        or (trial_id is not None and (not isinstance(trial_id, UUID) or not trial_id.int))
    ):
        raise ValueError("Worker custody is invalid")


def _reserve_capacity(profile: WorkerHostProfile, worker_id: UUID, now: datetime) -> None:
    """Reserve every enforcing metric before a worker can dispatch."""
    from engine.models import CapacityDraw, CapacityReservation

    from ._capacity_admit import admit_range_capacity

    partition = _worker_partition(profile)
    budgets = list(
        CapacityReservation.objects.select_for_update()
        .filter(
            event_ref=profile.capacity_scope_ref, released_at__isnull=True, window_start__lte=now, window_end__gt=now
        )
        .order_by("metric_name")
    )
    if CapacityDraw.objects.filter(draw_key=worker_id).exists():
        raise ValueError("Worker capacity identity conflicts")
    _validate_worker_budgets(profile, budgets, partition)
    CapacityReservation.objects.filter(pk__in=[budget.pk for budget in budgets]).update(release_on_absence=True)
    result = admit_range_capacity(profile.capacity_scope_ref, draw_key=worker_id, now=now)
    _validate_worker_verdicts(result.verdicts)


def _validate_worker_budgets(
    profile: WorkerHostProfile, budgets: list[CapacityReservation], partition: PartitionRef
) -> None:
    """Require one adequate enforcing budget per admitted metric in the same partition."""
    by_metric = {budget.metric_name: budget for budget in budgets}
    if any(budget.partition_name != partition.name for budget in budgets):
        raise ValueError("Worker capacity partition is unavailable")
    if len(by_metric) != len(budgets) or any(
        name not in by_metric or by_metric[name].enforcement != "enforcing" or by_metric[name].unit_amount < cost
        for name, cost in profile.capacity_demand.items()
    ):
        raise ValueError("Worker capacity reservation is unavailable")


def _validate_worker_verdicts(verdicts: tuple[MetricVerdict, ...]) -> None:
    """Refuse absent, uncertain or advisory draw results."""
    from shared.capacity import CapacityOutcome, EnforcementMode

    if not verdicts or any(
        item.outcome != CapacityOutcome.ADMITTED or item.enforcement != EnforcementMode.ENFORCING for item in verdicts
    ):
        raise ValueError("Worker capacity reservation refused")


def _worker_partition(profile: WorkerHostProfile) -> PartitionRef:
    """Resolve an approved capacity partition against this deployment's substrate."""
    catalog = getattr(settings, "CAPACITY_PLANNING_CATALOG", None)
    partition = catalog.partitions.get(profile.capacity_partition) if catalog is not None else None
    if (
        not getattr(settings, "CAPACITY_PLANNING_ENABLED", False)
        or partition is None
        or (partition.provider, partition.backend, partition.account, partition.region)
        != ("gcp", "gce", settings.GCP_PROJECT_ID, settings.GCP_REGION)
    ):
        raise ValueError("Worker capacity partition is unavailable")
    return partition


def get_disposable_worker(credential: CredentialContext, worker_id: UUID) -> WorkerView:
    """Return bounded lifecycle state after current range-read authorization."""
    return _view(_authorized_worker(credential, worker_id, "range.read"))


def bind_worker_trial(credential: CredentialContext, worker_id: UUID, trial_id: UUID) -> WorkerView:
    """An unassigned worker can acquire one immutable trial identity."""
    from ._worker_retirement import _lock_worker

    _authorized_worker(credential, worker_id, "range.manage")
    if not isinstance(trial_id, UUID) or not trial_id.int:
        raise ValueError("Worker trial identity is invalid")
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        if resolve_local_credential(credential) != credential:
            raise ValueError("Worker trial authority changed")
        if worker.trial_id == trial_id:
            return _view(worker)
        if worker.trial_id is not None or worker.retirement_at is not None or worker.terminal_at is not None:
            raise ValueError("Worker trial conflicts")
        worker.trial_id = trial_id
        worker.save(update_fields=["trial_id"])
        _audit(credential, worker, "worker_trial_bind")
        return _view(worker)


def worker_credential_scope(worker_id: UUID) -> ResourceScope | None:
    """Composition-only SQL ancestry, never a permission or fallback scope."""
    from engine.models import DisposableWorker

    from ._range_authority import project_range_authority

    row = DisposableWorker.objects.filter(pk=worker_id).first()
    return project_range_authority(row.request_id).scope if row is not None else None


def _authorized_worker(credential: CredentialContext, worker_id: UUID, action: str) -> DisposableWorker:
    """Resolve retained custody and require the exact current range action."""
    from engine.models import DisposableWorker

    from ._range_authority import require_native_range_action

    row = DisposableWorker.objects.select_related("range").get(pk=worker_id)
    require_native_range_action(credential, row.request_id, action)
    return row


def _view(row: DisposableWorker) -> WorkerView:
    """Project lifecycle facts without apparatus inputs or guest credentials."""
    from ._worker_qualification import has_current_qualification

    row.range.refresh_from_db()
    return WorkerView(
        row.pk,
        row.experiment_id,
        row.trial_id,
        row.range.status,
        row.deadline,
        row.terminal_at is not None,
        row.holds.filter(released_at__isnull=True).exists(),
        row.recovery_required,
        has_current_qualification(row),
        row.recovery_reason,
        row.recovery_attempts,
        row.next_recovery_at,
        row.retirement_at is not None,
    )


def _audit(
    credential: CredentialContext, worker: DisposableWorker | None, action: str, facts: dict[str, str] | None = None
) -> None:
    """Record a strict principal-attributed worker transition."""
    from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields

    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=worker.range_id if worker else 0,
            entity_ref=str(worker.pk) if worker else "worker-policy",
            action="update",
            new_state={"worker_action": action, **(facts or {})},
            **principal_actor_fields(credential.principal),
        ),
        strict=True,
    )


def worker_profile_binding(name: str = DEFAULT_PROFILE) -> WorkerProfileBinding:
    """Return the exact current digest of a published host profile for a batch to retain."""
    from engine.models import WorkerPolicyRecord

    record = WorkerPolicyRecord.objects.filter(pk=1).first()
    if record is None:
        raise WorkerProfileError("No worker policy is published")
    return WorkerProfileBinding(name=name, digest=WorkerPolicy.model_validate(record.configuration).select(name).digest)


def _admitted_profile(
    worker: DisposableWorker | None, policy: WorkerPolicy, binding: WorkerProfileBinding | None
) -> WorkerHostProfile:
    """Recover a retained apparatus; the batch's exact binding selects only new workers."""
    if worker is None:
        return policy.select(binding or DEFAULT_PROFILE)
    profile = WorkerHostProfile.model_validate(worker.profile)
    if profile.digest != worker.profile_digest:
        raise ValueError("Worker apparatus binding changed")
    return profile


def _check_worker_limits(policy: WorkerPolicy) -> None:
    """Check aggregate bounds under the caller's locked worker-policy mutex."""
    from engine.models import DisposableWorker

    live = DisposableWorker.objects.filter(terminal_at__isnull=True)
    if live.count() >= policy.max_live or live.exclude(range__status="ready").count() >= policy.max_provisioning:
        raise ValueError("Worker capacity limit reached")


def _validate_created_worker(worker: DisposableWorker, profile: WorkerHostProfile, scope: ResourceScope) -> None:
    """Fence actual placement and exact public custody before the admission commits."""
    zone = worker.range.placement_zone
    if zone and zone.rsplit("-", 1)[0] != _worker_partition(profile).region:
        raise ValueError("Worker capacity partition does not match placement")
    if resolve_credential_scope(TargetRef("range", worker.pk)) != scope:
        raise ValueError("Worker range identity conflicts")
