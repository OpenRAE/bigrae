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
