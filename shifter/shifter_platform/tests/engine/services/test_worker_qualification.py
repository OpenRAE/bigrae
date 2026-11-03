"""Private management qualification uses the local daemon and bounded output."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.engine.services.test_disposable_workers import apparatus, create, tenant

__all__ = ["apparatus", "tenant"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def guest(apparatus, monkeypatch):
    import sys

    import asyncssh

    from engine.models import DisposableWorker, Range, RangeManagementAccess

    worker = create(apparatus)
    key = asyncssh.generate_private_key("ssh-ed25519")
    private = key.export_private_key().decode()
    host_public = key.export_public_key().decode()
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.secretmanager",
        SimpleNamespace(
            SecretManagerServiceClient=lambda: SimpleNamespace(
                access_secret_version=lambda **kwargs: SimpleNamespace(payload=SimpleNamespace(data=private.encode()))
            )
        ),
    )
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    member = {
        "uuid": "provision.node.web#0",
        "asset_type": "gce_vm",
        "instance_id": "synthetic-worker-vm",
        "private_ip": "10.51.0.2",
        "gcp_host_ssh_key_secret_ref": "projects/synthetic/secrets/key/versions/1",
        "gcp_host_ssh_username": "range-management",
        "gcp_host_ssh_port": 22,
        "gcp_host_public_key": host_public,
    }
    Range.objects.filter(pk=row.range_id).update(status="ready", provisioned_instances=[member])
    runtime = Range.objects.get(pk=row.range_id)
    RangeManagementAccess.objects.create(
        range=runtime,
        operation_id=runtime.provisioner_operation_id,
        resource_generation=runtime.resource_generation,
        bindings={
            member["uuid"]: {
                "ssh_key_secret_ref": member["gcp_host_ssh_key_secret_ref"],
                "host_public_key": host_public,
                "username": member["gcp_host_ssh_username"],
                "port": 22,
            }
        },
    )
    return SimpleNamespace(worker=worker, row=row, member=member, key=key, host_public=host_public)


def test_qualification_pins_host_identity_and_records_bounded_facts(apparatus, guest, monkeypatch):
    import asyncssh

    from engine.services import qualify_disposable_worker

    payload = json.dumps(
        {
            "machine_id": "a" * 32,
            "daemon_id": "b" * 36,
            "docker_version": apparatus.profile["docker_version"],
            "daemon_count": 1,
        }
    )
    stream = SimpleNamespace(read=AsyncMock(side_effect=[payload, ""]))
    process = SimpleNamespace(
        stdout=stream,
        stderr=SimpleNamespace(read=AsyncMock(return_value="")),
        stdin=SimpleNamespace(write=lambda value: None, write_eof=lambda: None),
        wait_closed=AsyncMock(),
        exit_status=0,
        close=lambda: None,
    )

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create_process(self, command):
            assert command == "sudo -n python3 -"
            return process

    def connect(host, **kwargs):
        assert host == guest.member["private_ip"]
        assert kwargs["known_hosts"] is not None
        return Connection()

    monkeypatch.setattr(asyncssh, "connect", connect)
    result = qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
    assert result.daemon_identity != "b" * 36
    assert result.vm_identity and result.machine_identity
    guest.row.refresh_from_db()
    assert guest.row.qualification["profile_digest"] == guest.row.profile_digest


def test_qualification_refuses_public_or_missing_host_identity_before_secrets(apparatus, guest):
    from engine.models import Range
    from engine.services import qualify_disposable_worker

    for change in ({"private_ip": "8.8.8.8"}, {"instance_id": ""}):
        Range.objects.filter(pk=guest.row.range_id).update(provisioned_instances=[guest.member | change])
        with pytest.raises(ValueError):
            qualify_disposable_worker(apparatus.credential, guest.worker.worker_id)
