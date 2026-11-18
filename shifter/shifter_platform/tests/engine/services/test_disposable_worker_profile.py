"""Apparatus admission uses the native host plan and exact image contract."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest


def _compiled_plan(fixture="worker-host.sdl.yaml"):
    from shared.raes.dispatch_port import ShifterDispatchResult
    from shared.raes.package_loader import launch_raes_package

    plans = []

    class Port:
        def realize(self, plan, participant_access=()):
            plans.append(plan)
            return ShifterDispatchResult("synthetic-worker", True, "accepted")

    path = Path(__file__).parents[1] / "fixtures" / fixture
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


def observed_hardware():
    """Provider settings that GCE reports for the default synthetic worker."""
    return {
        "machine_type": "e2-custom-2-8192",
        "enable_secure_boot": True,
        "nic_type": "",
        "disk_interface": "SCSI",
        "image_id": "1234567890123456789",
    }


def arm_profile_data():
    """A C4A worker that selects the ARM64 hardware and boot choices."""
    data = profile_data()
    data["image"] |= {
        "machine_type": "c4a-standard-2",
        "disk_type": "hyperdisk-balanced",
        "nic_type": "GVNIC",
        "disk_interface": "NVME",
        "enable_secure_boot": False,
    }
    return data


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


def test_arm_worker_selects_predefined_shape_and_boot_choices():
    from shared.disposable_workers import WorkerHostProfile

    profile = WorkerHostProfile.model_validate(arm_profile_data())
    assert profile.hardware == {
        "provision.node.web": {
            "machine_type": "c4a-standard-2",
            "enable_secure_boot": False,
            "image_id": "1234567890123456789",
            "nic_type": "GVNIC",
            "disk_interface": "NVME",
        }
    }


def test_default_hardware_choices_keep_the_existing_profile_identity():
    from shared.disposable_workers import WorkerHostProfile

    data = profile_data()
    legacy = WorkerHostProfile.model_validate(data)
    data["image"] |= {"nic_type": "", "disk_interface": "", "enable_secure_boot": True}
    explicit = WorkerHostProfile.model_validate(data)
    assert explicit.digest == legacy.digest
    assert legacy.hardware == {
        "provision.node.web": {
            "machine_type": "e2-custom-2-8192",
            "enable_secure_boot": True,
            "image_id": "1234567890123456789",
        }
    }
    # A one-VM profile keeps its earlier serialized shape, so retained digests stay valid.
    assert {"trial_host", "additional_hosts"}.isdisjoint(legacy.model_dump(mode="json"))
    assert WorkerHostProfile.model_validate(arm_profile_data()).digest != legacy.digest


@pytest.mark.parametrize("machine_type", ["c4a-standard-4", "e2-medium", "e2-custom-2-8192", "c4a-standard-2-lssd"])
def test_explicit_machine_type_must_state_the_plan_cpu_count(machine_type):
    from shared.disposable_workers import WorkerHostProfile

    data = arm_profile_data()
    data["image"]["machine_type"] = machine_type
    with pytest.raises(ValueError):
        WorkerHostProfile.model_validate(data)


@pytest.mark.parametrize("value", ["false", 0, None])
def test_secure_boot_choice_requires_a_boolean(value):
    from shared.disposable_workers import WorkerHostProfile

    data = arm_profile_data()
    data["image"]["enable_secure_boot"] = value
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


def test_a_single_unnamed_policy_profile_loads_as_default_and_selection_is_exact():
    """#2924: older policies keep working; a binding refuses a changed or missing profile."""
    from shared.disposable_workers import WorkerPolicy, WorkerProfileBinding, WorkerProfileError

    policy = WorkerPolicy.model_validate({"profile": profile_data(), "max_live": 2, "max_provisioning": 2})
    profile = policy.select("default")
    assert set(policy.profiles) == {"default"}
    assert policy.select(WorkerProfileBinding(name="default", digest=profile.digest)) == profile
    for binding in ("missing", WorkerProfileBinding(name="default", digest="sha256:" + "0" * 64)):
        with pytest.raises(WorkerProfileError):
            policy.select(binding)


def two_vm_profile_data():
    """A workstation and a victim VM; the workstation runs the trial."""
    data = profile_data()
    data["plan"] = _compiled_plan("worker-hosts.sdl.yaml")
    data["trial_host"] = "provision.node.workstation"
    data["additional_hosts"] = {
        "provision.node.victim": {
            "image": data["image"] | {"image_ref": "projects/synthetic/global/images/victim-v1"},
            "image_id": "2234567890123456789",
        }
    }
    data["capacity_demand"] = {"vcpu": 4.0, "instances": 2.0}
    return data


def test_two_vm_profile_gives_each_vm_its_image_and_hardware():
    """#2947: every VM has an exact image; the trial host is named."""
    from shared.disposable_workers import WorkerHostProfile

    profile = WorkerHostProfile.model_validate(two_vm_profile_data())
    assert [node.address for node in profile.nodes] == ["provision.node.victim", "provision.node.workstation"]
    assert profile.trial_host_address == "provision.node.workstation"
    assert profile.hardware["provision.node.victim"]["image_id"] == "2234567890123456789"
    assert profile.hardware["provision.node.workstation"]["image_id"] == "1234567890123456789"


@pytest.mark.parametrize(
    "change",
    [
        {"trial_host": ""},
        {"trial_host": "provision.node.victim"},
        {"additional_hosts": {}},
        {"capacity_demand": {"vcpu": 2.0, "instances": 2.0}},
        {"capacity_demand": {"vcpu": 4.0, "instances": 1.0}},
    ],
)
def test_two_vm_profile_refuses_an_unnamed_trial_host_a_missing_image_or_short_capacity(change):
    from shared.disposable_workers import WorkerHostProfile

    with pytest.raises(ValueError):
        WorkerHostProfile.model_validate(two_vm_profile_data() | change)
