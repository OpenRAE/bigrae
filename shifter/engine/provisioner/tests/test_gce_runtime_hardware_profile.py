"""Administrator hardware choices survive validation, pinning, and GCE rendering."""

import hashlib
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from shared.runtime_plugin_binding import RuntimeTargetImageProfile

from config import GCERangeImageProfile, gce_image_profile_fingerprint
from gcp_range_cell_host_binding import GCEInstanceBindingError, assert_runtime_hardware_binding
from gcp_range_cell_resources import instance_resource
from raes_gce_image import resolve_gce_image, resolve_gce_image_from_runtime_profile
from raes_plan import RaesPlanNode
from tests.test_gcp_range_cell_resources import _config, _instance, _plan


def _runtime(**overrides):
    return RuntimeTargetImageProfile(
        provider="gcp", image_ref="projects/example/global/images/arm-guest-v1", **overrides
    )


_ARM = {
    "machine_type": "c4a-standard-2",
    "disk_type": "hyperdisk-balanced",
    "nic_type": "GVNIC",
    "disk_interface": "NVME",
    "enable_secure_boot": False,
}


def _from_runtime_profile(node):
    retained = RuntimeTargetImageProfile.model_validate_json(_runtime(**_ARM).model_dump_json())
    return resolve_gce_image_from_runtime_profile(node, retained)


def _from_worker_candidate(node):
    candidate = {"source_version": "", "image_ref": "projects/example/global/images/arm-guest-v1", **_ARM}
    return resolve_gce_image(node, [candidate])


@pytest.mark.parametrize("resolve", [_from_runtime_profile, _from_worker_candidate])
def test_selected_arm_hardware_survives_snapshot_and_rendering(resolve):
    node = RaesPlanNode(address="node.guest", name="guest", os_family="linux", count=1, network_addresses=())
    profile = resolve(node)
    instance = _instance(os_type="linux")
    instance["profile"] = profile
    instance["image_profile_fingerprint"] = gce_image_profile_fingerprint(profile)
    body = instance_resource(_plan(), instance, _config(), ssh_public_key="ssh-ed25519 test")
    assert body["machine_type"].endswith("/c4a-standard-2")
    assert body["network_interfaces"][0]["nic_type"] == "GVNIC"
    assert body["disks"][0]["interface"] == "NVME"
    assert body["disks"][0]["initialize_params"]["disk_type"].endswith("/hyperdisk-balanced")
    assert body["shielded_instance_config"] == {
        "enable_secure_boot": False,
        "enable_vtpm": True,
        "enable_integrity_monitoring": True,
    }


def test_default_boot_protection_and_interface_defaults_are_preserved():
    body = instance_resource(_plan(), _instance(), _config(), ssh_public_key="ssh-ed25519 test")
    assert body["shielded_instance_config"]["enable_secure_boot"] is True
    assert "nic_type" not in body["network_interfaces"][0]
    assert "interface" not in body["disks"][0]
    dumped = _runtime().model_dump(mode="json")
    assert not {"nic_type", "disk_interface", "enable_secure_boot"}.intersection(dumped)


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_secure_boot_choice_requires_a_boolean(value):
    with pytest.raises(ValueError):
        _runtime(enable_secure_boot=value)


@pytest.mark.parametrize(
    "fields",
    [
        {"nic_type": "GVNIC"},
        {"disk_interface": "NVME"},
        {"enable_secure_boot": False},
    ],
)
def test_aws_rejects_gcp_only_hardware_choices(fields):
    with pytest.raises(ValueError):
        RuntimeTargetImageProfile(provider="aws", image_ref="ami-0123456789abcdef0", **fields)


@pytest.mark.parametrize("fields", [{"nic_type": "invalid"}, {"disk_interface": "invalid"}])
def test_unknown_gcp_interface_values_are_rejected(fields):
    with pytest.raises(ValueError):
        _runtime(**fields)


def test_legacy_profile_fingerprint_is_stable():
    profile = GCERangeImageProfile(source_image="projects/example/global/images/guest-v1")
    legacy = asdict(profile)
    for key in [
        "nic_type",
        "disk_interface",
        "enable_secure_boot",
        "source_image_id",
        "participant_readiness_contract",
        "participant_readiness_manifest_sha256",
    ]:
        legacy.pop(key, None)
    expected = hashlib.sha256(json.dumps(legacy, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:24]
    assert gce_image_profile_fingerprint(profile) == expected


@pytest.mark.parametrize("fields", [{"nic_type": "GVNIC"}, {"disk_interface": "NVME"}, {"enable_secure_boot": False}])
def test_nondefault_hardware_changes_profile_identity(fields):
    profile = GCERangeImageProfile(source_image="projects/example/global/images/guest-v1")
    assert gce_image_profile_fingerprint(replace(profile, **fields)) != gce_image_profile_fingerprint(profile)


@pytest.mark.parametrize("changed", [None, "machine_type", "shielded_instance_config", "network_interfaces", "disks"])
def test_provider_readback_requires_the_selected_hardware(changed):
    instance = _instance(os_type="linux")
    instance["profile"] = replace(
        instance["profile"], nic_type="GVNIC", disk_interface="NVME", enable_secure_boot=False
    )
    actual = SimpleNamespace(
        machine_type="zones/example/machineTypes/e2-standard-4",
        shielded_instance_config=SimpleNamespace(enable_secure_boot=False),
        network_interfaces=[SimpleNamespace(nic_type=SimpleNamespace(name="GVNIC"))],
        disks=[SimpleNamespace(boot=True, interface=SimpleNamespace(name="NVME"))],
    )
    if changed is None:
        assert_runtime_hardware_binding(actual, instance)
    else:
        setattr(actual, changed, None)
        with pytest.raises(GCEInstanceBindingError):
            assert_runtime_hardware_binding(actual, instance)
