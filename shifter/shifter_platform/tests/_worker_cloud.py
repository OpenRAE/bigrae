"""External cloud, secret-store and guest observations for native worker tests."""

import pytest


@pytest.fixture
def worker_cloud(apparatus, monkeypatch):
    """Drive native result application while replacing only external peers."""
    import time

    from django.utils import timezone
    from shifter_adapter_sdk.runtime import canonical_digest

    from engine.models import DisposableWorker, ProvisionerLaunchIntent
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result, _ready_payload

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
                        "worker_observations": {
                            member["uuid"]: {
                                "vm_identity": canonical_digest(f"vm-{runtime.pk}"),
                                "machine_identity": canonical_digest(f"machine-{runtime.pk}"),
                                "daemon_identity": canonical_digest(f"daemon-{runtime.pk}"),
                                "docker_version": apparatus.profile["docker_version"],
                                "daemon_count": 1,
                                "observed_at": timezone.now().isoformat(),
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
