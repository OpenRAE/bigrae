"""Apparatus admission uses the native host plan and exact image contract."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest


def _compiled_plan():
    from shared.raes.dispatch_port import ShifterDispatchResult
    from shared.raes.package_loader import launch_raes_package

    plans = []

    class Port:
        def realize(self, plan, participant_access=()):
            plans.append(plan)
            return ShifterDispatchResult("synthetic-worker", True, "accepted")

    path = Path(__file__).parents[1] / "fixtures/worker-host.sdl.yaml"
    assert launch_raes_package(scenario_path=path, port=Port()).accepted
    return plans[0]


def profile_data():
    return {
        "plan": _compiled_plan(),
        "image": {
            "provider": "gcp",
            "image_ref": "projects/synthetic/global/images/docker-host-v1",
            "machine_type": "",
            "disk_size_gb": 20,
            "management_ssh_username": "range-management",
        },
        "provenance_digest": "sha256:" + "a" * 64,
        "image_id": "1234567890123456789",
        "docker_version": "28.5.1",
        "capacity_scope_ref": str(uuid4()),
        "capacity_partition": "synthetic",
        "capacity_demand": {"vcpu": 2.0, "instances": 1.0},
        "egress_mode": "none",
    }


def test_valid_profile_retains_exact_plan_image_and_runtime():
    from shared.disposable_workers import WorkerHostProfile

    data = profile_data()
    profile = WorkerHostProfile.model_validate(data)
    assert profile.plan == data["plan"]
    assert profile.image.image_ref == data["image"]["image_ref"]
    assert profile.digest.startswith("sha256:")


def test_machine_override_cannot_understate_capacity_demand():
    from shared.disposable_workers import WorkerHostProfile

    data = profile_data()
    data["image"]["machine_type"] = "e2-standard-64"
    with pytest.raises(ValueError):
        WorkerHostProfile.model_validate(data)


def test_native_approved_egress_mode_is_accepted():
    from shared.disposable_workers import WorkerHostProfile

    data = profile_data()
    data["egress_mode"] = "status-quo"
    assert WorkerHostProfile.model_validate(data).egress_mode == "status-quo"


@pytest.mark.parametrize(
    "change", ["two-vms", "mutable-image", "no-image-id", "no-docker-pin", "wrong-cpu", "unknown-key"]
)
def test_invalid_apparatus_fails_before_admission(change):
    from shared.disposable_workers import WorkerHostProfile

    data = profile_data()
    if change == "two-vms":
        resource = deepcopy(data["plan"]["resources"]["provision.node.web"])
        resource["address"] = "provision.node.extra"
        data["plan"]["resources"][resource["address"]] = resource
    elif change == "mutable-image":
        data["image"]["image_ref"] = "projects/synthetic/global/images/family/docker"
    elif change == "no-docker-pin":
        data["docker_version"] = "latest"
    elif change == "no-image-id":
        data.pop("image_id")
    elif change == "wrong-cpu":
        data["capacity_demand"]["vcpu"] = 0.5
    else:
        data["inner_sdl"] = "untrusted"
    with pytest.raises(ValueError):
        WorkerHostProfile.model_validate(data)
