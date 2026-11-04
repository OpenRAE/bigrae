"""Engine qualifies accepted host observations without management secret access."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone
from shifter_adapter_sdk.runtime import canonical_digest

from tests.engine.services.test_disposable_workers import apparatus, create, tenant

__all__ = ["apparatus", "tenant"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def guest(apparatus):
    from engine.models import DisposableWorker, Range, WorkerHostObservation

    worker = create(apparatus)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    member = {"uuid": "provision.node.web#0", "asset_type": "gce_vm", "instance_id": "synthetic-worker-vm"}
    Range.objects.filter(pk=row.range_id).update(status="ready", provisioned_instances=[member])
    runtime = Range.objects.get(pk=row.range_id)
    observed = {
        "vm_identity": canonical_digest("numeric-provider-identity"),
        "machine_identity": canonical_digest("a" * 32),
        "daemon_identity": canonical_digest("b" * 36),
        "docker_version": apparatus.profile["docker_version"],
        "daemon_count": 1,
        "observed_at": timezone.now().isoformat(),
    }
    record = WorkerHostObservation.objects.create(
        range=runtime,
        operation_id=runtime.provisioner_operation_id,
        resource_generation=runtime.resource_generation,
        observations={member["uuid"]: observed},
    )
    return SimpleNamespace(worker=worker, row=row, member=member, record=record, observed=observed)


def test_qualification_pins_host_identity_and_records_bounded_facts(apparatus, guest, monkeypatch):
    import asyncssh

    from engine.services import get_disposable_worker, qualify_disposable_worker

    def forbidden_management_access(*args, **kwargs):
        raise AssertionError("Portal must not access host-management secrets or SSH")

    monkeypatch.setattr("engine.secrets.get_ssh_key", forbidden_management_access)
    monkeypatch.setattr(asyncssh, "connect", forbidden_management_access)
    result = qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
    assert result.daemon_identity == guest.observed["daemon_identity"]
    assert result.vm_identity == guest.observed["vm_identity"]
    guest.row.refresh_from_db()
    assert guest.row.qualification["profile_digest"] == guest.row.profile_digest
    assert get_disposable_worker(apparatus.credential, guest.worker.worker_id).qualified


@pytest.mark.parametrize(
    "change",
    [
        {"docker_version": "0.0.0"},
        {"daemon_count": 2},
        {"daemon_count": True},
        {"observed_at": (timezone.now() - timedelta(seconds=901)).isoformat()},
        {"observed_at": (timezone.now() + timedelta(days=1)).isoformat()},
        {"machine_identity": "raw-guest-identity"},
        {"ssh_key_secret_ref": "forbidden"},
    ],
)
def test_untrusted_observation_never_qualifies(apparatus, guest, change):
    from engine.services import qualify_disposable_worker

    guest.record.observations = {guest.member["uuid"]: guest.observed | change}
    guest.record.save()
    with pytest.raises(ValueError):
        qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
    guest.row.refresh_from_db()
    assert not guest.row.qualification


@pytest.mark.parametrize("change", ["operation", "generation", "member", "deadline", "retirement", "status"])
def test_current_binding_is_required(apparatus, guest, change, monkeypatch):
    from engine.models import DisposableWorker, Range
    from engine.services import qualify_disposable_worker

    if change in {"operation", "generation"}:
        setattr(guest.record, "operation_id" if change == "operation" else "resource_generation", uuid4())
        guest.record.save()
    elif change == "member":
        Range.objects.filter(pk=guest.row.range_id).update(provisioned_instances=[guest.member | {"uuid": "other#0"}])
    elif change == "status":
        Range.objects.filter(pk=guest.row.range_id).update(status="destroying")
    elif change == "deadline":
        future = guest.row.deadline + timedelta(seconds=1)
        monkeypatch.setattr(timezone, "now", lambda: future)
    else:
        DisposableWorker.objects.filter(pk=guest.row.pk).update(retirement_at=timezone.now())
    with pytest.raises(ValueError):
        qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)


def test_expired_or_old_generation_qualification_is_not_current(apparatus, guest):
    from engine.models import Range
    from engine.services import get_disposable_worker, qualify_disposable_worker

    qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
    Range.objects.filter(pk=guest.row.range_id).update(resource_generation=uuid4())
    assert not get_disposable_worker(apparatus.credential, guest.worker.worker_id).qualified


def test_effect_transaction_rechecks_deadline(apparatus, guest, monkeypatch):
    from engine.services import _worker_qualification, qualify_disposable_worker

    original = _worker_qualification._store_qualification

    def expired_before_store(*args, **kwargs):
        future = guest.row.deadline + timedelta(seconds=1)
        monkeypatch.setattr(timezone, "now", lambda: future)
        return original(*args, **kwargs)

    monkeypatch.setattr(_worker_qualification, "_store_qualification", expired_before_store)
    with pytest.raises(ValueError, match="binding changed"):
        qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)


@pytest.mark.parametrize("change", ["missing", "foreign", "extra", "legacy"])
def test_result_projection_requires_exact_immutable_targets(apparatus, guest, change):
    from engine.models import WorkerHostObservation
    from engine.services._worker_observations import persist_worker_observations

    runtime = guest.record.range
    WorkerHostObservation.objects.all().delete()
    observed = {guest.member["uuid"]: guest.observed}
    if change == "missing":
        observed = {}
    elif change == "foreign":
        observed = {"foreign#0": guest.observed}
    elif change == "extra":
        observed["foreign#0"] = guest.observed
    payload = {"worker_observations": observed}
    if change == "legacy":
        payload = {"management_access": {guest.member["uuid"]: {}}}
    with pytest.raises(ValueError, match="admitted targets"):
        persist_worker_observations(SimpleNamespace(operation_id=runtime.provisioner_operation_id), payload, runtime)
    assert not WorkerHostObservation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_migration_refuses_active_workers_and_clears_only_retired_references(apparatus, guest):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from engine.models import OperationInput

    immutable = OperationInput.objects.get(operation_id=guest.record.operation_id)
    original = immutable.envelope
    before = [("engine", "0122_merge_worker_and_cloud_custody")]
    after = [("engine", "0123_worker_host_observations")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    try:
        old.get_model("engine", "RangeManagementAccess").objects.update_or_create(
            range_id=guest.row.range_id,
            defaults={
                "operation_id": guest.record.operation_id,
                "resource_generation": guest.record.resource_generation,
                "bindings": {"historical": "private-reference"},
            },
        )
        with pytest.raises(RuntimeError, match="Retire existing"):
            MigrationExecutor(connection).migrate(after)
        assert old.get_model("engine", "RangeManagementAccess").objects.count() >= 1
        old.get_model("engine", "DisposableWorker").objects.filter(pk=guest.row.pk).update(terminal_at=timezone.now())
        MigrationExecutor(connection).migrate(after)
        from engine.models import WorkerHostObservation

        assert not WorkerHostObservation.objects.exists()
        immutable.refresh_from_db()
        assert immutable.envelope == original
    finally:
        old.get_model("engine", "DisposableWorker").objects.filter(pk=guest.row.pk).update(terminal_at=timezone.now())
        MigrationExecutor(connection).migrate(after)


@pytest.mark.parametrize("identity", ["vm_identity", "machine_identity", "daemon_identity"])
def test_distinct_workers_cannot_share_an_identity(apparatus, guest, identity):
    from engine.models import DisposableWorker, Range, WorkerHostObservation
    from engine.services import qualify_disposable_worker

    qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
    other = create(apparatus)
    worker = DisposableWorker.objects.get(pk=other.worker_id)
    Range.objects.filter(pk=worker.range_id).update(status="ready", provisioned_instances=[guest.member])
    observed = guest.observed | {
        key: canonical_digest(f"another-{key}")
        for key in ("vm_identity", "machine_identity", "daemon_identity")
        if key != identity
    }
    WorkerHostObservation.objects.create(
        range_id=worker.range_id,
        operation_id=worker.range.provisioner_operation_id,
        resource_generation=worker.range.resource_generation,
        observations={guest.member["uuid"]: observed},
    )
    with pytest.raises(ValueError, match="not independent"):
        qualify_disposable_worker(apparatus.credential, other.worker_id)
