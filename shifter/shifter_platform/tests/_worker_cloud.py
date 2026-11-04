"""External cloud, secret-store and guest observations for native worker tests."""

import json

import pytest


@pytest.fixture
def worker_cloud(apparatus, monkeypatch):
    """Drive native result application while replacing only external peers."""
    import sys
    import time
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import asyncssh

    from engine.models import DisposableWorker, ProvisionerLaunchIntent
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result, _ready_payload

    key = asyncssh.generate_private_key("ssh-ed25519")
    private = key.export_private_key()
    public = key.export_public_key().decode()
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.secretmanager",
        SimpleNamespace(
            SecretManagerServiceClient=lambda: SimpleNamespace(
                access_secret_version=lambda **kwargs: SimpleNamespace(payload=SimpleNamespace(data=private))
            )
        ),
    )

    class Connection:
        def __init__(self, host):
            self.host = host

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create_process(self, command):
            assert command == "sudo -n python3 -"
            identity = self.host.rsplit(".", 1)[1].zfill(32)
            payload = json.dumps(
                {
                    "machine_id": identity,
                    "daemon_id": identity,
                    "docker_version": apparatus.profile["docker_version"],
                    "daemon_count": 1,
                }
            )
            return SimpleNamespace(
                stdout=SimpleNamespace(read=AsyncMock(side_effect=[payload, ""])),
                stderr=SimpleNamespace(read=AsyncMock(return_value="")),
                stdin=SimpleNamespace(write=lambda value: None, write_eof=lambda: None),
                wait_closed=AsyncMock(),
                exit_status=0,
                close=lambda: None,
            )

    monkeypatch.setattr(asyncssh, "connect", lambda host, **kwargs: Connection(host))

    def provider_progress(_seconds):
        for worker in DisposableWorker.objects.select_related("range"):
            runtime = worker.range
            intent = ProvisionerLaunchIntent.objects.get(operation_id=runtime.provisioner_operation_id)
            if runtime.status == "provisioning":
                member = {
                    "uuid": "provision.node.web#0",
                    "name": "web",
                    "os_type": "linux",
                    "subnet_name": "lan",
                    "participant_access_channels": [],
                    "participant_access_usernames": {},
                    "instance_id": f"synthetic-{runtime.pk}",
                    "private_ip": f"10.51.0.{runtime.pk % 200 + 2}",
                }
                _apply_result(
                    intent,
                    ResultStep.RAES_TERMINAL_READY,
                    _ready_payload(intent)
                    | {
                        "members": [member],
                        "management_access": {
                            member["uuid"]: {
                                "ssh_key_secret_ref": "projects/synthetic/secrets/key/versions/1",
                                "username": "range-management",
                                "port": 22,
                                "host_public_key": public,
                            }
                        },
                    },
                )
            elif runtime.status == "destroying":
                _apply_result(
                    intent,
                    ResultStep.RAES_TERMINAL_DESTROYED,
                    {
                        "raes_status": "succeeded",
                        "cleanup_inventory": {
                            "outcome": "VERIFIED_ABSENT",
                            "scope": {"request_id": str(worker.request_id)},
                            "residual_categories": [],
                        },
                    },
                )

    monkeypatch.setattr(time, "sleep", provider_progress)
