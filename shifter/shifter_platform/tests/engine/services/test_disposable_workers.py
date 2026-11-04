"""Disposable worker admission, immutable custody, holds and capacity retention."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone

from tests.cms.test_runtime_plugins import tenant
from tests.engine.services.test_disposable_worker_profile import profile_data

__all__ = ["tenant"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def apparatus(tenant, settings, allow_all_policy, monkeypatch):
    from engine.models import CapacityReservation
    from engine.services import configure_worker_policy
    from shared.authorization import RelationshipState
    from shared.capacity import PartitionRef
    from shared.capacity.catalog import CapacityCatalog
    from shared.deployment import resolve_audit_deployment_scope
    from workspaces.services import add_account_member, hierarchy_target_scope

    relationships = set()
    allow_all_policy.write_relationships = lambda change: relationships.add(change.grant_tuple)
    allow_all_policy.read_relationships = lambda change: RelationshipState(change.grant_tuple in relationships, False)
    actor, organization = tenant
    actor.policy_accounts.add(None)
    add_account_member(organization.account.uuid, actor.credential.principal)
    settings.CLOUD_PROVIDER = "gcp"
    settings.AUDIT_DEPLOYMENT_SCOPE = resolve_audit_deployment_scope()
    settings.GCP_PROJECT_ID = "synthetic"
    settings.GCP_REGION = "synthetic-region"
    settings.CAPACITY_PLANNING_ENABLED = True
    settings.CAPACITY_PLANNING_CATALOG = CapacityCatalog(
        partitions={
            "synthetic": PartitionRef(
                name="synthetic", provider="gcp", account="synthetic", region="synthetic-region", backend="gce"
            )
        }
    )
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gce")
    settings.ENGINE_TASK_CLUSTER = "synthetic-jobs"
    settings.ENGINE_TASK_DEFINITION = "example.test/provisioner@sha256:" + "1" * 64
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "synthetic-worker"
    data = profile_data()
    now = timezone.now()
    for metric, cost in data["capacity_demand"].items():
        CapacityReservation.objects.create(
            event_ref=data["capacity_scope_ref"],
            partition_name="synthetic",
            metric_name=metric,
            amount=4 * cost,
            unit_amount=cost,
            enforcement="enforcing",
            window_start=now - timezone.timedelta(hours=1),
            window_end=now + timezone.timedelta(hours=1),
        )
    configure_worker_policy(actor.credential, {"profile": data, "max_live": 2, "max_provisioning": 2})
    return SimpleNamespace(
        credential=actor.credential,
        scope=hierarchy_target_scope("organization", organization.uuid),
        experiment=uuid4(),
        profile=data,
    )


def create(apparatus, **kwargs):
    from engine.services import create_disposable_worker

    return create_disposable_worker(
        apparatus.credential,
        scope=apparatus.scope,
        worker_id=kwargs.pop("worker_id", uuid4()),
        experiment_id=kwargs.pop("experiment_id", apparatus.experiment),
        **kwargs,
    )


def test_create_commits_native_launch_and_durable_custody(apparatus):
    from cms.models import RangeInstance
    from engine.models import CapacityDraw, DisposableWorker, OperationInput, ProvisionerLaunchIntent, Range

    result = create(apparatus, trial_id=uuid4())
    row = DisposableWorker.objects.get(pk=result.worker_id)
    runtime = Range.objects.get(pk=row.range_id)
    assert runtime.cms_range_uuid == row.pk
    assert runtime.owner_principal_uuid == apparatus.credential.principal.uuid
    assert runtime.range_backend == "gce" and runtime.resource_generation
    assert row.experiment_id == apparatus.experiment
    assert not RangeInstance.objects.exists()
    assert CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).count() == 2
    intent = ProvisionerLaunchIntent.objects.get()
    payload = OperationInput.objects.get(operation_id=intent.operation_id).envelope["payload"]
    assert payload["plan"] == apparatus.profile["plan"]
    candidate = next(iter(payload["image_candidates"].values()))[0]
    assert candidate["image_id"] == apparatus.profile["image_id"]
    assert intent.payload["resource"] == "raes-range"


def test_idempotent_replay_rejects_changed_experiment_and_trial(apparatus):
    worker_id, trial_id = uuid4(), uuid4()
    create(apparatus, worker_id=worker_id, trial_id=trial_id)
    assert create(apparatus, worker_id=worker_id, trial_id=trial_id).worker_id == worker_id
    for kwargs in ({"experiment_id": uuid4(), "trial_id": trial_id}, {"trial_id": uuid4()}):
        with pytest.raises(ValueError):
            create(apparatus, worker_id=worker_id, **kwargs)


def test_create_replay_retains_apparatus_after_operator_policy_change(apparatus):
    from engine.models import DisposableWorker, ProvisionerLaunchIntent, WorkerPolicyRecord
    from engine.services import configure_worker_policy

    worker = create(apparatus)
    original = DisposableWorker.objects.get(pk=worker.worker_id).profile
    policy = WorkerPolicyRecord.objects.get().configuration
    policy["profile"]["docker_version"] = "28.5.2"
    configure_worker_policy(apparatus.credential, policy)
    assert create(apparatus, worker_id=worker.worker_id).worker_id == worker.worker_id
    assert DisposableWorker.objects.get(pk=worker.worker_id).profile == original
    assert ProvisionerLaunchIntent.objects.count() == 1


def test_wrong_partition_budget_cannot_admit_a_worker(apparatus):
    from engine.models import CapacityReservation, DisposableWorker

    CapacityReservation.objects.update(partition_name="another-region")
    with pytest.raises(ValueError):
        create(apparatus)
    assert not DisposableWorker.objects.exists()


@pytest.mark.parametrize("change", ["experiment", "profile", "trial-reset", "scope", "delete"])
def test_bulk_updates_cannot_erase_worker_custody(apparatus, change):
    from django.db import IntegrityError, transaction

    from engine.models import DisposableWorker, Range

    worker = create(apparatus, trial_id=uuid4())
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    with pytest.raises(IntegrityError), transaction.atomic():
        if change == "experiment":
            DisposableWorker.objects.filter(pk=row.pk).update(experiment_id=uuid4())
        elif change == "profile":
            DisposableWorker.objects.filter(pk=row.pk).update(profile_digest="sha256:" + "b" * 64)
        elif change == "trial-reset":
            DisposableWorker.objects.filter(pk=row.pk).update(trial_id=None)
        elif change == "scope":
            Range.objects.filter(pk=row.range_id).update(owner_principal_uuid=uuid4())
        else:
            DisposableWorker.objects.filter(pk=row.pk).delete()


def test_global_limit_counts_failed_and_provisioning_workers(apparatus):
    from engine.models import Range

    create(apparatus)
    create(apparatus)
    Range.objects.update(status="failed")
    with pytest.raises(ValueError, match="capacity"):
        create(apparatus)


@pytest.mark.parametrize("mode", ["absent", "advisory", "insufficient", "expired"])
def test_capacity_refusal_has_no_worker_or_launch_effect(apparatus, mode):
    from engine.models import CapacityDraw, CapacityReservation, DisposableWorker, ProvisionerLaunchIntent

    if mode == "absent":
        CapacityReservation.objects.all().delete()
    elif mode == "advisory":
        CapacityReservation.objects.update(enforcement="advisory")
    elif mode == "expired":
        CapacityReservation.objects.update(window_end=timezone.now() - timezone.timedelta(seconds=1))
    else:
        CapacityReservation.objects.filter(metric_name="vcpu").update(amount=0)
    with pytest.raises(ValueError, match="capacity"):
        create(apparatus)
    assert not DisposableWorker.objects.exists()
    assert not ProvisionerLaunchIntent.objects.exists()
    assert not CapacityDraw.objects.exists()


@pytest.mark.parametrize("provider,backend", [("aws", "gce"), ("gcp", "gdc"), ("gcp", "unknown")])
def test_unsupported_backend_refused_before_effects(apparatus, settings, monkeypatch, provider, backend):

    from engine.models import DisposableWorker

    settings.CLOUD_PROVIDER = provider
    monkeypatch.setenv("GCP_RANGE_BACKEND", backend)
    with pytest.raises(ValueError, match="backend"):
        create(apparatus)
    assert not DisposableWorker.objects.exists()


def test_expired_capacity_with_live_worker_stays_reserved(apparatus):
    from engine.models import CapacityDraw, CapacityReservation
    from engine.services import reconcile_capacity_budgets
    from engine.services._capacity_plan_persistence import _committed_reservation

    create(apparatus)
    now = timezone.now()
    CapacityReservation.objects.update(window_end=now - timezone.timedelta(seconds=1))
    reconcile_capacity_budgets(now=now)
    assert not CapacityReservation.objects.filter(released_at__isnull=False).exists()
    assert not CapacityDraw.objects.filter(released_at__isnull=False).exists()
    assert _committed_reservation("synthetic", "vcpu", now, now + timezone.timedelta(hours=1)) == 8


def test_holds_fence_native_destruction_and_expiry(apparatus):
    from engine.models import DisposableWorker, Range
    from engine.services import (
        acquire_worker_hold,
        commit_prepared_range_lifecycle,
        prepare_system_range_cleanup,
        reconcile_disposable_workers,
        retire_disposable_worker,
    )

    worker = create(apparatus)
    Range.objects.update(status="ready")
    hold = acquire_worker_hold(apparatus.credential, worker.worker_id, reason="evidence")
    with pytest.raises(ValueError, match="hold"):
        retire_disposable_worker(apparatus.credential, worker.worker_id)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    with pytest.raises(ValueError, match="hold"):
        commit_prepared_range_lifecycle(prepare_system_range_cleanup(row.request_id))
    reconcile_disposable_workers(now=hold.review_at + timezone.timedelta(seconds=1))
    row.refresh_from_db()
    assert row.recovery_required
    assert Range.objects.get(pk=row.range_id).status == "ready"


@pytest.mark.parametrize("preparing", [False, True])
def test_optional_software_uses_apparatus_protocol_without_pack(apparatus, preparing, settings):
    from shifter_adapter_sdk.runtime import RuntimeInput

    from engine.models import RuntimePluginInstallation, RuntimePluginInvocation, WorkerPolicyRecord
    from engine.services import configure_worker_policy, install_runtime_plugin

    manifest = {
        "protocol": "bigrae.runtime-plugin/v2",
        "plugin_id": "synthetic.worker",
        "version": "1.0",
        "distribution": "synthetic-worker",
        "entry_point": "worker",
        "worker_image": "registry.example.test/adapters/synthetic@sha256:" + "a" * 64,
        "capabilities": ["guest.configure", "guest.verify"],
        "required_bindings": ["host"],
    }
    if preparing:
        manifest["capabilities"].append("provision.prepare")
        manifest["provisioning_concerns"] = ["worker-settings"]
    installation = install_runtime_plugin(apparatus.credential, apparatus.scope.organization_uuid, manifest)
    RuntimePluginInstallation.objects.filter(pk=installation.id).update(state="ready")
    configuration = WorkerPolicyRecord.objects.get().configuration
    configuration["profile"]["software"] = {
        "installation_id": str(installation.id),
        "organization_uuid": str(apparatus.scope.organization_uuid),
        "manifest_digest": installation.manifest_digest,
        "bindings": {"targets": {"host": "provision.node.web"}},
    }
    configure_worker_policy(apparatus.credential, configuration)
    worker = create(apparatus)
    invocations = list(
        RuntimePluginInvocation.objects.filter(
            request_id__in=[
                __import__("engine.models", fromlist=["DisposableWorker"])
                .DisposableWorker.objects.get(pk=worker.worker_id)
                .request_id
            ]
        )
    )
    assert len(invocations) == (4 if preparing else 3)
    for invocation in invocations:
        request = RuntimeInput.model_validate(invocation.input)
        assert request.apparatus_digest and request.pack_digest is None
        assert set(request.targets) == {"host"}

    if preparing:
        from cryptography.fernet import Fernet
        from django.db import transaction
        from shifter_adapter_sdk.runtime import RuntimePlan

        from engine.models import DisposableWorker, OperationInput, ProvisionerLaunchIntent
        from engine.services import retire_disposable_worker
        from engine.services._runtime_plugin_preparation import approve_invocation, retain_preparation
        from shared.raes.operation_input import parse_raes_operation_input

        settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
        invocation = next(item for item in invocations if item.phase == "prepare")
        request = RuntimeInput.model_validate(invocation.input)
        result = RuntimePlan(
            protocol=request.protocol,
            invocation_id=request.invocation_id,
            input_digest=request.digest,
            phase="prepare",
            status="planned",
            provisioning_values=[],
        )
        approval = approve_invocation(invocation, request, result)
        retained = DisposableWorker.objects.get(pk=worker.worker_id)
        with transaction.atomic():
            retain_preparation(retained.range, approval)
        from shared.operation_results import ResultStep
        from tests.engine.services.test_native_warm_retirement import _apply_result

        provision = ProvisionerLaunchIntent.objects.get(payload__operation="provision")
        _apply_result(
            provision,
            ResultStep.RAES_TERMINAL_FAILED,
            {"reason_code": "cloud_operation_failed", "diagnostic": "Synthetic guest configuration failure"},
        )
        retire_disposable_worker(apparatus.credential, worker.worker_id)
        cleanup = ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").get()
        payload = parse_raes_operation_input(
            OperationInput.objects.get(operation_id=cleanup.operation_id).envelope["payload"]
        )
        assert payload.runtime_preparation == approval
        assert payload.runtime_plugin.apparatus_digest and "pack_digest" not in payload.runtime_plugin.model_dump(
            mode="json"
        )


def test_trial_binding_is_single_use_and_identity_does_not_grant_access(apparatus):
    from engine.services import bind_worker_trial, get_disposable_worker
    from shared.authorization import AuthorizationDecision, DecisionKind, port

    worker = create(apparatus)
    trial = uuid4()
    assert bind_worker_trial(apparatus.credential, worker.worker_id, trial).trial_id == trial
    assert bind_worker_trial(apparatus.credential, worker.worker_id, trial).trial_id == trial
    with pytest.raises(ValueError):
        bind_worker_trial(apparatus.credential, worker.worker_id, uuid4())
    provider = port._provider_factory()
    provider.check = lambda request: AuthorizationDecision(DecisionKind.DENIED, "policy_denied")
    with pytest.raises(PermissionError):
        get_disposable_worker(apparatus.credential, worker.worker_id)


def test_failed_teardown_is_bounded_and_retains_capacity(apparatus):
    from engine.models import CapacityDraw, DisposableWorker, ProvisionerLaunchIntent
    from engine.services import reconcile_disposable_workers, retire_disposable_worker
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result

    worker = create(apparatus)
    provision = ProvisionerLaunchIntent.objects.get(payload__operation="provision")
    _apply_result(
        provision,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": "cloud_operation_failed", "diagnostic": "Synthetic partial failure"},
    )
    retire_disposable_worker(apparatus.credential, worker.worker_id)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    cleanup = ProvisionerLaunchIntent.objects.get(payload__operation="destroy")
    _apply_result(
        cleanup,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": "cloud_operation_failed", "diagnostic": "Synthetic teardown failure"},
    )
    for _ in range(row.max_recovery_attempts + 2):
        row.refresh_from_db()
        reconcile_disposable_workers(now=row.next_recovery_at + timezone.timedelta(seconds=1))
    row.refresh_from_db()
    assert row.recovery_required and row.terminal_at is None
    assert row.recovery_attempts == row.max_recovery_attempts
    assert CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).count() == 2


def test_destroyed_status_without_provider_absence_does_not_release_capacity(apparatus):
    from engine.models import CapacityDraw, DisposableWorker, Range
    from engine.services import retire_disposable_worker

    worker = create(apparatus)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    Range.objects.filter(pk=row.range_id).update(status="destroyed")
    retire_disposable_worker(apparatus.credential, worker.worker_id)
    row.refresh_from_db()
    assert row.terminal_at is None
    assert CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).count() == 2


def test_worker_identity_cannot_shadow_an_existing_cms_range(apparatus):
    from cms.models import RangeInstance
    from engine.models import DisposableWorker

    pending = RangeInstance.objects.create(
        scenario_id="synthetic-pending",
        status="pending",
        scope_kind="account",
        account_id=__import__("workspaces.services", fromlist=["resolve_range_scope_binding"])
        .resolve_range_scope_binding(apparatus.scope)
        .account_id,
        owner_principal_uuid=apparatus.credential.principal.uuid,
    )
    with pytest.raises(ValueError):
        create(apparatus, worker_id=pending.uuid)
    assert not DisposableWorker.objects.exists()


def test_hold_cannot_promise_preservation_during_provisioning(apparatus):
    from engine.services import acquire_worker_hold

    worker = create(apparatus)
    with pytest.raises(ValueError, match="ready"):
        acquire_worker_hold(apparatus.credential, worker.worker_id, reason="evidence")


def test_native_scope_move_cannot_rehome_worker_custody(apparatus):
    from engine.models import DisposableWorker, Range
    from engine.services import prepare_range_scope_move

    worker = create(apparatus)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    Range.objects.filter(pk=row.range_id).update(status="ready")
    with pytest.raises(ValueError, match="Worker"):
        prepare_range_scope_move(apparatus.credential, row.request_id, apparatus.scope)


def test_accepted_provider_absence_settles_capacity_without_waiting_for_retry(apparatus):
    from engine.models import CapacityDraw, DisposableWorker, ProvisionerLaunchIntent
    from engine.services import reconcile_disposable_workers, retire_disposable_worker
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result

    worker = create(apparatus)
    provision = ProvisionerLaunchIntent.objects.get(payload__operation="provision")
    _apply_result(
        provision,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": "cloud_operation_failed", "diagnostic": "Synthetic partial provision"},
    )
    retire_disposable_worker(apparatus.credential, worker.worker_id)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    cleanup = ProvisionerLaunchIntent.objects.get(payload__operation="destroy")
    _apply_result(
        cleanup,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {
            "raes_status": "succeeded",
            "cleanup_inventory": {
                "outcome": "VERIFIED_ABSENT",
                "residual_categories": [],
                "scope": {
                    "provider": "gcp",
                    "request_id": str(row.request_id),
                    "resource_generation": str(row.range.resource_generation),
                },
            },
        },
    )
    reconcile_disposable_workers(worker_ids=(row.pk,))
    row.refresh_from_db()
    assert row.terminal_at is not None
    assert not CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).exists()


def test_qualification_storage_rejects_cloned_daemon_identity(apparatus):
    from django.db import IntegrityError, transaction

    from engine.models import DisposableWorker

    first, second = create(apparatus), create(apparatus)
    evidence = {"daemon_identity": "sha256:" + "a" * 64, "machine_identity": "sha256:" + "b" * 64}
    DisposableWorker.objects.filter(pk=first.worker_id).update(qualification=evidence)
    with pytest.raises(IntegrityError), transaction.atomic():
        DisposableWorker.objects.filter(pk=second.worker_id).update(qualification=evidence)


def test_provision_cancellation_retains_capacity_and_rejects_late_readiness(apparatus):
    from engine.models import CapacityDraw, DisposableWorker, ProvisionerLaunchIntent
    from engine.services import retire_disposable_worker
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result, _ready_payload

    worker = create(apparatus)
    retire_disposable_worker(apparatus.credential, worker.worker_id)
    intent = ProvisionerLaunchIntent.objects.get(payload__operation="provision")
    assert intent.interrupt_state != "none"
    _apply_result(intent, ResultStep.RAES_TERMINAL_READY, _ready_payload(intent))
    row = DisposableWorker.objects.select_related("range").get(pk=worker.worker_id)
    assert row.range.status == "destroying"
    assert row.terminal_at is None
    assert CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).count() == 2


@pytest.mark.parametrize("operation", ["destroy", "cancel"])
def test_legacy_integer_reference_cannot_mutate_native_worker(apparatus, operation):
    from engine.models import DisposableWorker
    from engine.services import cancel_range, destroy_range
    from shared.schemas import RangeRef

    worker = create(apparatus)
    row = DisposableWorker.objects.select_related("range").get(pk=worker.worker_id)
    reference = RangeRef(
        request_id=row.request_id, range_id=row.range_id, user_id=row.range.user_id, status=row.range.status
    )
    with pytest.raises(PermissionError):
        (destroy_range if operation == "destroy" else cancel_range)(reference)
    row.range.refresh_from_db()
    assert row.range.status == "provisioning"


@pytest.mark.django_db(transaction=True)
def test_replay_policy_calls_do_not_hold_sql_locks(apparatus, allow_all_policy):
    from django.db import connection

    observations = []
    previous = allow_all_policy.check

    def check(request):
        observations.append(connection.in_atomic_block)
        return previous(request)

    allow_all_policy.check = check
    worker_id = uuid4()
    create(apparatus, worker_id=worker_id)
    create(apparatus, worker_id=worker_id)
    assert observations and not any(observations)


@pytest.mark.django_db(transaction=True)
def test_authority_publication_precedes_dispatch_and_runs_without_sql_locks(apparatus, allow_all_policy):
    from django.db import connection

    from engine.models import DisposableWorker, ProvisionerLaunchIntent
    from shared.authorization import RelationshipState

    observed = []

    def write(change):
        assert not connection.in_atomic_block
        assert DisposableWorker.objects.count() == 1
        assert not ProvisionerLaunchIntent.objects.exists()
        observed.append(change.grant_tuple)

    def read(change):
        assert not connection.in_atomic_block
        return RelationshipState(change.grant_tuple in observed, False)

    allow_all_policy.write_relationships = write
    allow_all_policy.read_relationships = read
    result = create(apparatus)
    assert len(observed) == 1
    assert observed[0].object == f"range:{result.worker_id}"
    assert observed[0].relation == ("organization" if apparatus.scope.organization_uuid else "account")
    assert DisposableWorker.objects.get(pk=result.worker_id).authorization_publication_state == "confirmed"
    assert ProvisionerLaunchIntent.objects.count() == 1


def test_unknown_authority_publication_retains_custody_without_launch_and_replays(apparatus, allow_all_policy):
    from engine.models import CapacityDraw, DisposableWorker, ProvisionerLaunchIntent
    from shared.authorization import RelationshipState

    worker_id = uuid4()
    original = allow_all_policy.read_relationships
    allow_all_policy.read_relationships = lambda change: RelationshipState(False, False)
    with pytest.raises(ValueError, match="authority publication"):
        create(apparatus, worker_id=worker_id)
    row = DisposableWorker.objects.get(pk=worker_id)
    assert row.authorization_publication_state == "unresolved"
    assert not ProvisionerLaunchIntent.objects.exists()
    assert CapacityDraw.objects.filter(draw_key=worker_id, released_at__isnull=True).count() == 2
    allow_all_policy.read_relationships = original
    create(apparatus, worker_id=worker_id)
    assert ProvisionerLaunchIntent.objects.count() == 1
    row.refresh_from_db()
    assert row.authorization_publication_state == "confirmed"


def test_authority_publication_cannot_switch_provider_binding(apparatus, allow_all_policy):
    from engine.models import DisposableWorker, ProvisionerLaunchIntent
    from shared.authorization import RelationshipState

    worker_id = uuid4()
    allow_all_policy.read_relationships = lambda change: RelationshipState(False, False)
    with pytest.raises(ValueError):
        create(apparatus, worker_id=worker_id)
    allow_all_policy.model_id = "different-model"
    with pytest.raises(ValueError):
        create(apparatus, worker_id=worker_id)
    assert DisposableWorker.objects.get(pk=worker_id).authorization_model_id == "test-model"
    assert not ProvisionerLaunchIntent.objects.exists()


def test_multiple_holders_own_their_release_and_operator_override_is_explicit(apparatus):
    from engine.models import Range
    from engine.services import acquire_worker_hold, release_worker_hold, retire_disposable_worker
    from management.services import create_service_principal
    from shared.authorization import AuthorizationContractError, CredentialCeiling
    from shared.credentials import CredentialContext
    from tests._credential_helpers import persisted_credential

    collector = persisted_credential(
        CredentialContext(
            create_service_principal("Synthetic evidence collector"),
            "service",
            uuid4(),
            CredentialCeiling(frozenset({"range.read", "range.manage"})),
            frozenset({"authorization:range.read", "authorization:range.manage"}),
        )
    )
    worker = create(apparatus)
    Range.objects.update(status="ready")
    first = acquire_worker_hold(apparatus.credential, worker.worker_id, reason="evidence")
    second = acquire_worker_hold(collector, worker.worker_id, reason="capture")
    assert first.owner_principal_uuid != second.owner_principal_uuid
    assert acquire_worker_hold(collector, worker.worker_id, reason="capture").hold_id == second.hold_id
    with pytest.raises(PermissionError):
        release_worker_hold(collector, first.hold_id)
    with pytest.raises(AuthorizationContractError, match="ceiling"):
        release_worker_hold(collector, first.hold_id, operator_override=True)
    release_worker_hold(apparatus.credential, first.hold_id)
    with pytest.raises(ValueError, match="hold"):
        retire_disposable_worker(apparatus.credential, worker.worker_id)
    assert release_worker_hold(apparatus.credential, second.hold_id, operator_override=True).released
    assert retire_disposable_worker(apparatus.credential, worker.worker_id).status == "destroying"


def test_unpublished_worker_expiry_retains_native_cleanup_authority(apparatus, allow_all_policy):
    from engine.models import DisposableWorker, ProvisionerLaunchIntent
    from engine.services import reconcile_disposable_workers
    from shared.authorization import RelationshipState

    worker_id = uuid4()
    allow_all_policy.read_relationships = lambda change: RelationshipState(False, False)
    with pytest.raises(ValueError, match="authority publication"):
        create(apparatus, worker_id=worker_id)
    worker = DisposableWorker.objects.get(pk=worker_id)
    reconcile_disposable_workers(now=worker.deadline + timezone.timedelta(seconds=1))
    worker.refresh_from_db()
    assert worker.retirement_at is not None
    assert worker.terminal_at is None
    assert not ProvisionerLaunchIntent.objects.filter(payload__operation="provision").exists()
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").exists()
