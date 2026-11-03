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
from shared.disposable_workers import WorkerHostProfile, WorkerPolicy
from shared.identity_scope import ResourceScope
from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose, evaluate_gcp_backend_admission

if TYPE_CHECKING:
    from engine.models import DisposableWorker


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


def _installation_authority(credential: CredentialContext) -> CredentialContext:
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
) -> WorkerView:
    """Atomically reserve global limits, capacity and native durable dispatch."""
    from engine.models import DisposableWorker, Range, WorkerPolicyRecord
    from management.services import human_principal_user_id
    from workspaces.services import resolve_range_scope_binding

    from ._principal_range_create import prepare_raes_range_creation
    from ._raes_range import RangeBindings, create_raes_range, dispatch_created_raes_range

    admission = _worker_backend()
    _validate_worker_custody(scope, worker_id, experiment_id, trial_id)
    current = resolve_current_credential(credential)
    resolved = resolve_range_scope_binding(scope, member=current.principal)
    user_id = human_principal_user_id(current.principal) if current.principal.kind == "human" else None
    record = WorkerPolicyRecord.objects.get(pk=1)
    policy = WorkerPolicy.model_validate(record.configuration)
    bindings = RangeBindings(credential=current, resource_scope=scope, cms_range_uuid=worker_id, defer_dispatch=True)
    prepared = prepare_raes_range_creation(bindings, resolved.workspace_id, user_id, policy.profile.plan)
    bindings = replace(bindings, prepared_creation=prepared)
    now = timezone.now()
    replayed = False
    with transaction.atomic():
        locked_scope = resolve_range_scope_binding(scope, member=current.principal, for_update=True)
        if locked_scope != resolved:
            raise ValueError("Worker scope changed")
        record = WorkerPolicyRecord.objects.select_for_update().get(pk=1)
        if record.configuration != policy.model_dump(mode="json"):
            raise ValueError("Worker policy changed")
        existing = DisposableWorker.objects.select_related("range").filter(pk=worker_id).first()
        if existing is not None:
            runtime = existing.range
            actual_scope = (runtime.scope_kind, runtime.account_id, runtime.organization_id, runtime.workspace_id)
            expected_scope = (resolved.kind, resolved.account_id, resolved.organization_id, resolved.workspace_id)
            if actual_scope != expected_scope or (
                existing.experiment_id,
                existing.trial_id,
                existing.profile_digest,
                runtime.owner_principal_uuid,
            ) != (experiment_id, trial_id, policy.profile.digest, current.principal.uuid):
                raise ValueError("Worker replay conflicts")
            worker, replayed = existing, True
        else:
            live = DisposableWorker.objects.filter(terminal_at__isnull=True)
            provisioning = live.exclude(range__status="ready")
            if live.count() >= policy.max_live or provisioning.count() >= policy.max_provisioning:
                raise ValueError("Worker capacity limit reached")
            _reserve_capacity(policy.profile, worker_id, now)
            request_id = uuid4()
            created = create_raes_range(
                request_id=request_id,
                user_id=user_id,
                compiled_plan=policy.profile.plan,
                workspace_id=resolved.workspace_id,
                egress_mode=policy.profile.egress_mode,
                backend_admission=admission,
                bindings=bindings,
            )
            runtime = Range.objects.get(uuid=created.range_id)
            worker = DisposableWorker.objects.create(
                id=worker_id,
                range=runtime,
                request_id=request_id,
                experiment_id=experiment_id,
                trial_id=trial_id,
                profile=policy.profile.model_dump(mode="json"),
                profile_digest=policy.profile.digest,
                capacity_scope_ref=policy.profile.capacity_scope_ref,
                deadline=now + timedelta(seconds=policy.lifetime_seconds),
                max_recovery_attempts=policy.recovery_attempts,
                hold_review_seconds=policy.hold_review_seconds,
                next_recovery_at=now + timedelta(seconds=policy.lifetime_seconds),
            )
            from ._worker_software import pin_worker_software

            if resolve_credential_scope(TargetRef("range", worker_id)) != scope:
                raise ValueError("Worker range identity conflicts")
            pin_worker_software(policy.profile, runtime, scope)
            _audit(current, worker, "worker_create")
    from engine.models import ProvisionerLaunchIntent

    from ._worker_relationships import publish_worker_relationships
    from ._worker_retirement import _lock_worker

    publish_worker_relationships(worker_id)
    if replayed:
        _authorized_worker(current, worker_id, "range.read")
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        # A concurrent deadline or operator retirement must win over deferred launch.
        if worker.retirement_at is not None or worker.terminal_at is not None:
            raise ValueError("Worker retirement already admitted")
        if not ProvisionerLaunchIntent.objects.filter(
            authority_resource_uuid=worker.pk, payload__operation="provision"
        ).exists():
            dispatch_created_raes_range(worker.request_id, credential=current, prepared_creation=prepared)
    return _view(worker)


def _validate_worker_custody(scope: ResourceScope, worker_id: UUID, experiment_id: UUID, trial_id: UUID | None) -> None:
    if (
        scope.kind != "account"
        or any(not isinstance(value, UUID) or not value.int for value in (worker_id, experiment_id))
        or (trial_id is not None and (not isinstance(trial_id, UUID) or not trial_id.int))
    ):
        raise ValueError("Worker custody is invalid")


def _reserve_capacity(profile: WorkerHostProfile, worker_id: UUID, now: datetime) -> None:
    from engine.models import CapacityDraw, CapacityReservation
    from shared.capacity import CapacityOutcome, EnforcementMode

    from ._capacity_admit import admit_range_capacity

    budgets = list(
        CapacityReservation.objects.select_for_update()
        .filter(
            event_ref=profile.capacity_scope_ref, released_at__isnull=True, window_start__lte=now, window_end__gt=now
        )
        .order_by("metric_name")
    )
    by_metric = {budget.metric_name: budget for budget in budgets}
    if CapacityDraw.objects.filter(draw_key=worker_id).exists():
        raise ValueError("Worker capacity identity conflicts")
    if len(by_metric) != len(budgets) or any(
        name not in by_metric or by_metric[name].enforcement != "enforcing" or by_metric[name].unit_amount < cost
        for name, cost in profile.capacity_demand.items()
    ):
        raise ValueError("Worker capacity reservation is unavailable")
    CapacityReservation.objects.filter(pk__in=[budget.pk for budget in budgets]).update(release_on_absence=True)
    result = admit_range_capacity(profile.capacity_scope_ref, draw_key=worker_id, now=now)
    if not result.verdicts or any(
        item.outcome != CapacityOutcome.ADMITTED or item.enforcement != EnforcementMode.ENFORCING
        for item in result.verdicts
    ):
        raise ValueError("Worker capacity reservation refused")


def get_disposable_worker(credential: CredentialContext, worker_id: UUID) -> WorkerView:
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
    from engine.models import DisposableWorker

    from ._range_authority import require_native_range_action

    row = DisposableWorker.objects.select_related("range").get(pk=worker_id)
    require_native_range_action(credential, row.request_id, action)
    return row


def _view(row: DisposableWorker) -> WorkerView:
    row.range.refresh_from_db(fields=["status"])
    return WorkerView(
        row.pk,
        row.experiment_id,
        row.trial_id,
        row.range.status,
        row.deadline,
        row.terminal_at is not None,
        row.holds.filter(released_at__isnull=True).exists(),
        row.recovery_required,
        bool(row.qualification),
        row.recovery_reason,
        row.recovery_attempts,
        row.next_recovery_at,
    )


def _audit(
    credential: CredentialContext, worker: DisposableWorker | None, action: str, facts: dict[str, str] | None = None
) -> None:
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
