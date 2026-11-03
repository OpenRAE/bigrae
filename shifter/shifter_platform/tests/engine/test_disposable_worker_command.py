"""Worker CLI authenticates native proof and exposes bounded operator state."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from tests.engine.services.test_disposable_workers import apparatus, create, tenant

__all__ = ["apparatus", "tenant"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def proof(apparatus, tmp_path):
    from django.contrib.auth import get_user_model

    from management.services import human_principal_user_id
    from shared.api_tokens.models import ApiToken

    user = get_user_model().objects.get(pk=human_principal_user_id(apparatus.credential.principal))
    _, raw = ApiToken.create_token(
        name="Synthetic worker command",
        created_by=user,
        scopes=[
            "authorization:installation.manage_cloud_authority",
            "authorization:organization.launch_range",
            "authorization:range.read",
            "authorization:range.manage",
            "authorization:range.access",
        ],
    )
    path = tmp_path / "worker-proof"
    path.write_text(raw)
    path.chmod(0o600)
    return path


def test_inspect_uses_native_proof_and_returns_no_guest_credentials(apparatus, proof):
    worker = create(apparatus)
    output = StringIO()
    call_command("disposable_workers", "inspect", credential_file=str(proof), worker_id=worker.worker_id, stdout=output)
    result = json.loads(output.getvalue())
    assert result["worker_id"] == str(worker.worker_id)
    assert result["status"] == "provisioning"
    assert "profile" not in result and "private_key" not in result


def test_command_rejects_public_proof_without_leaking_input(apparatus, proof):
    proof.chmod(0o644)
    with pytest.raises(CommandError) as failure:
        call_command(
            "disposable_workers",
            "smoke",
            credential_file=str(proof),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
        )
    assert str(proof) not in str(failure.value)


def test_invalid_smoke_timeout_refuses_before_creating_workers(apparatus, proof):
    from engine.models import DisposableWorker

    with pytest.raises(CommandError):
        call_command(
            "disposable_workers",
            "smoke",
            credential_file=str(proof),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
            timeout=0,
        )
    assert not DisposableWorker.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_smoke_uses_two_real_native_lifecycles_and_verifies_cleanup(apparatus, proof, monkeypatch):
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
    output = StringIO()
    call_command(
        "disposable_workers",
        "smoke",
        credential_file=str(proof),
        scope_kind="organization",
        scope_id=apparatus.scope.organization_uuid,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["independent_workers"] == 2 and result["cleanup_verified"]
    assert DisposableWorker.objects.filter(terminal_at__isnull=False).count() == 2
