"""PostgreSQL contention proves the deployment-wide worker admission bound."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from tests.engine.services.test_disposable_workers import apparatus, create, tenant

__all__ = ["apparatus", "tenant"]
pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def test_two_experiments_cannot_spend_the_same_global_slot(apparatus):
    from types import SimpleNamespace

    from engine.models import CapacityDraw, DisposableWorker, WorkerPolicyRecord
    from engine.services import configure_worker_policy
    from workspaces.models import Organization
    from workspaces.services import add_account_member, create_account, hierarchy_target_scope

    other_account = create_account(kind="team", name="Other synthetic worker account")
    other_organization = Organization.objects.get(account_id=other_account.id, is_default=True)
    add_account_member(other_account.uuid, apparatus.credential.principal)
    other = SimpleNamespace(
        **(vars(apparatus) | {"scope": hierarchy_target_scope("organization", other_organization.uuid)})
    )
    policy = WorkerPolicyRecord.objects.get().configuration
    policy.update(max_live=1, max_provisioning=1)
    configure_worker_policy(apparatus.credential, policy)
    first_locked, second_attempting, release = threading.Event(), threading.Event(), threading.Event()

    def launch(first):
        def trace(execute, sql, params, many, context):
            mutex = '"engine_workerpolicyrecord"' in sql and "FOR UPDATE" in sql
            if mutex and not first:
                second_attempting.set()
            result = execute(sql, params, many, context)
            if mutex and first:
                first_locked.set()
                assert release.wait(10)
            return result

        try:
            with connection.execute_wrapper(trace):
                try:
                    return create(apparatus if first else other).worker_id
                except ValueError as exc:
                    assert "capacity" in str(exc)
                    return None
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(launch, True)
        assert first_locked.wait(10)
        second = pool.submit(launch, False)
        try:
            assert second_attempting.wait(10)
            assert not second.done()
        finally:
            release.set()
        assert first.result(timeout=20) is not None
        assert second.result(timeout=20) is None
    assert DisposableWorker.objects.count() == 1
    assert CapacityDraw.objects.filter(released_at__isnull=True).count() == 2


def test_parallel_dispatch_does_not_invert_creation_ancestry_and_range_table_locks(apparatus, allow_all_policy):
    """Force deferred dispatch to meet another creation's exclusive subnet allocator."""
    from uuid import uuid4

    first_id = uuid4()
    publishing, allocating, readback, dispatch_lock = (threading.Event() for _ in range(4))
    original_read = allow_all_policy.read_relationships

    def read(change):
        if change.object == f"range:{first_id}":
            publishing.set()
            assert allocating.wait(10)
            readback.set()
        return original_read(change)

    allow_all_policy.read_relationships = read

    def launch(first):
        def trace(execute, sql, params, many, context):
            if not first and "LOCK TABLE mission_control_range IN EXCLUSIVE MODE" in sql:
                allocating.set()
                assert dispatch_lock.wait(10)
            if (
                first
                and readback.is_set()
                and "FOR UPDATE" in sql
                and ('"workspaces_account"' in sql or '"engine_workerpolicyrecord"' in sql)
            ):
                dispatch_lock.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(trace):
                return create(apparatus, **({"worker_id": first_id} if first else {})).worker_id
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(launch, True)
        assert publishing.wait(10)
        second = pool.submit(launch, False)
        assert first.result(timeout=30) == first_id
        assert second.result(timeout=30) != first_id


def test_creation_overlaps_verified_absence_settlement_without_deadlock(apparatus):
    """Meet a real capacity-row lock with native range/table locks in PostgreSQL."""
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
    budget_locked, settlement_attempting = threading.Event(), threading.Event()

    def run(creating):
        def trace(execute, sql, params, many, context):
            locking = "FOR UPDATE" in sql
            if not creating and locking and '"engine_workerpolicyrecord"' in sql:
                settlement_attempting.set()
            result = execute(sql, params, many, context)
            if not creating and locking and '"mission_control_range"' in sql:
                settlement_attempting.set()
            if creating and locking and '"engine_capacity_reservation"' in sql and not budget_locked.is_set():
                budget_locked.set()
                assert settlement_attempting.wait(10)
            return result

        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            with connection.execute_wrapper(trace):
                if creating:
                    return create(apparatus).worker_id
                return reconcile_disposable_workers(worker_ids=(worker.worker_id,))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        creation = pool.submit(run, True)
        if not budget_locked.wait(10):
            creation.result(timeout=1)
            pytest.fail("Creation never acquired the capacity reservation")
        settlement = pool.submit(run, False)
        assert creation.result(timeout=20) != worker.worker_id
        assert settlement.result(timeout=20) == 1
    row.refresh_from_db()
    assert row.terminal_at is not None
    assert not CapacityDraw.objects.filter(draw_key=row.pk, released_at__isnull=True).exists()
    assert DisposableWorker.objects.count() == 2
