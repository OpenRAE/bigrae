"""Ordinary native cleanup reuses accepted authority and keeps unknown custody."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import OperationInput, ProvisionerLaunchIntent, Range, RangeCleanupVerification
from engine.services import reconcile_range_cleanup_verification
from shared.operation_results import ResultStep
from tests.cms.conftest import make_pack as make_pack
from tests.cms.services.test_principal_content import content_actor as content_actor
from tests.cms.services.test_principal_range_launch import launch_actor as launch_actor
from tests.engine.services.test_native_warm_retirement import _apply_result

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.postgres]


@pytest.fixture
def ordinary_destroy(launch_actor):
    from cms.services import create_raes_native_range
    from engine.services import commit_prepared_range_lifecycle, prepare_system_range_cleanup

    actor = launch_actor
    result = create_raes_native_range(actor.credential, actor.source.scenario_id, scope=actor.scope)
    runtime = Range.objects.get(request__request_id=result.request_id)
    ProvisionerLaunchIntent.objects.filter(operation_id=runtime.provisioner_operation_id).update(status="SUCCEEDED")
    # Provider READY is outside this service test; creation and destroy authority
    # and their immutable queue/input records are real.
    Range.objects.filter(pk=runtime.pk).update(status="ready")
    assert commit_prepared_range_lifecycle(prepare_system_range_cleanup(result.request_id))
    runtime.refresh_from_db()
    original = ProvisionerLaunchIntent.objects.get(operation_id=runtime.provisioner_operation_id)
    _apply_result(
        original,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {
            "raes_status": "succeeded",
            "cleanup_inventory": {"outcome": "INCOMPLETE", "scope": {}, "residual_categories": []},
        },
    )
    runtime.refresh_from_db()
    assert runtime.status == "destroyed"
    return runtime, original


def test_scheduled_pass_retries_unknown_native_cleanup_after_delay_once(ordinary_destroy, monkeypatch):
    from cms.management.commands.reconcile_range_events import Command
    from engine.services._launch_authority import authorize_launch_authority

    runtime, original = ordinary_destroy
    old_input = OperationInput.objects.get(operation_id=original.operation_id).envelope
    generation = runtime.resource_generation
    assert reconcile_range_cleanup_verification() == 0
    moment = timezone.now() + timedelta(minutes=2)
    monkeypatch.setattr(timezone, "now", lambda: moment)
    Command()._run_once(stale_seconds=300, batch_size=25)
    runtime.refresh_from_db()
    assert runtime.status == "destroying"
    retry = ProvisionerLaunchIntent.objects.get(operation_id=runtime.provisioner_operation_id)
    assert retry.operation_id != original.operation_id
    assert retry.cleanup_origin_operation_uuid == original.cleanup_origin_operation_uuid
    assert retry.authority_binding_digest == original.authority_binding_digest
    assert runtime.resource_generation == generation
    assert OperationInput.objects.get(operation_id=original.operation_id).envelope == old_input
    authorize_launch_authority(retry, runtime)
    assert reconcile_range_cleanup_verification(now=moment) == 0
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").count() == 2


@pytest.mark.parametrize("status", ["pending", "provisioning", "ready", "destroying", "failed"])
def test_active_or_failed_lifecycle_is_not_an_unknown_terminal_retry(ordinary_destroy, status):
    runtime, _original = ordinary_destroy
    Range.objects.filter(pk=runtime.pk).update(status=status)
    assert reconcile_range_cleanup_verification(now=timezone.now() + timedelta(hours=1)) == 0
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").count() == 1


@pytest.mark.parametrize("evidence", ["verified", "missing", "stale-operation"])
def test_only_latest_current_unknown_evidence_can_select_a_retry(ordinary_destroy, evidence):
    runtime, original = ordinary_destroy
    if evidence == "missing":
        RangeCleanupVerification.objects.filter(operation_id=original.operation_id).delete()
    elif evidence == "stale-operation":
        Range.objects.filter(pk=runtime.pk).update(provisioner_operation_id=uuid4())
    else:
        RangeCleanupVerification.objects.create(
            request_id=runtime.request.request_id,
            operation_id=original.operation_id,
            outcome="VERIFIED_ABSENT",
            scope={},
            observed_at=timezone.now(),
        )
    assert reconcile_range_cleanup_verification(now=timezone.now() + timedelta(hours=1)) == 0
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").count() == 1


@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_recovery_batch_bound_is_checked_before_query(limit):
    with pytest.raises(ValueError, match="limit is invalid"):
        reconcile_range_cleanup_verification(limit=limit)


def test_command_isolates_recovery_failure_and_does_not_log_diagnostics(monkeypatch, caplog):
    from cms.management.commands.reconcile_range_events import Command
    from engine import services

    def unavailable(**kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_MARKER")

    monkeypatch.setattr(services, "reconcile_range_cleanup_verification", unavailable)
    Command()._reconcile_range_cleanup(25)
    assert "range cleanup recovery pass failed" in caplog.text
    assert "PRIVATE_PROVIDER_MARKER" not in caplog.text


def test_concurrent_passes_queue_one_native_retry(ordinary_destroy):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Barrier

    from django.db import close_old_connections, connections

    _runtime, _original = ordinary_destroy
    moment = timezone.now() + timedelta(minutes=2)
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return reconcile_range_cleanup_verification(now=moment)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(copy_context().run, attempt) for _ in range(2)]
        assert sorted(future.result(timeout=20) for future in pending) == [0, 1]
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").count() == 2


@pytest.mark.parametrize("kind", ["warm", "disposable"])
def test_separate_recovery_owners_are_not_retried_by_this_pass(ordinary_destroy, kind):
    from engine.models import DisposableWorker, WarmRangeGeneration

    runtime, _original = ordinary_destroy
    moment = timezone.now()
    if kind == "warm":
        WarmRangeGeneration.objects.create(
            range=runtime,
            bucket_id="synthetic-bucket",
            compatibility_digest="sha256:" + "a" * 64,
            effective_policy_fingerprint="sha256:" + "b" * 64,
            backend="gce",
            range_source="mission_control",
            capacity_partition="synthetic",
            capacity_scope_ref=uuid4(),
            capacity_draw_key=uuid4(),
            request_id=runtime.request.request_id,
            state="retiring",
        )
    else:
        DisposableWorker.objects.create(
            range=runtime,
            request_id=runtime.request.request_id,
            experiment_id=uuid4(),
            profile={},
            profile_digest="sha256:" + "c" * 64,
            capacity_scope_ref=uuid4(),
            deadline=moment,
            max_recovery_attempts=3,
            hold_review_seconds=60,
            next_recovery_at=moment,
        )
    assert reconcile_range_cleanup_verification(now=moment + timedelta(hours=1)) == 0
    assert ProvisionerLaunchIntent.objects.filter(payload__operation="destroy").count() == 1
