"""Binding checks for deterministic GCE participant hosts."""

from __future__ import annotations

from config import GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST
from gcp_range_cell_naming import _label_value
from gcp_range_cell_resources import HOST_PUBLIC_KEY_METADATA_KEY
from gcp_range_cell_types import InstancePlan, RangeCellPlan


class GCEInstanceBindingError(RuntimeError):
    """An existing deterministic VM does not belong to this range profile."""


def _host_public_key_from_instance(existing: object) -> str:
    """Recover the provisioner-issued host key instead of minting a mismatched one."""
    metadata = getattr(existing, "metadata", None)
    for item in getattr(metadata, "items", None) or []:
        if getattr(item, "key", None) == HOST_PUBLIC_KEY_METADATA_KEY:
            return str(getattr(item, "value", "") or "")
    return ""


def _existing_label(existing: object, key: str) -> str:
    """Read one label from a dict-like Compute instance response."""
    labels = getattr(existing, "labels", None)
    getter = getattr(labels, "get", None)
    if callable(getter):
        return str(getter(key, "") or "")
    return ""


def _assert_instance_image_binding(existing: object, instance: InstancePlan) -> None:
    """Reject a keyed deterministic VM whose recorded profile differs from the plan."""
    expected_key = instance["image_key"]
    if not expected_key:
        return
    actual_key = _existing_label(existing, "image-key")
    actual_profile = _existing_label(existing, "image-profile")
    if actual_key != expected_key or actual_profile != instance["image_profile_fingerprint"]:
        raise RuntimeError(
            "Existing GCE range instance has an image-profile binding that differs from the current plan; "
            f"ami_key={expected_key!r}. Recreate the range instead of reusing the drifted instance."
        )


def _assert_preconfigured_host_binding(existing: object, plan: RangeCellPlan, instance: InstancePlan) -> None:
    """Never adopt a participant host with different ownership or image policy."""
    assert_runtime_hardware_binding(existing, instance)
    if instance["profile"].bootstrap_capability != GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        return
    expected = {
        "managed-by": plan["labels"]["managed-by"],
        "range-id": plan["labels"]["range-id"],
        "image-key": _label_value(instance["image_key"] or "default"),
        "image-profile": instance["image_profile_fingerprint"],
    }
    if any(_existing_label(existing, key) != value for key, value in expected.items()):
        raise GCEInstanceBindingError("Existing GCE participant host has a conflicting range or image-profile binding")


def assert_runtime_hardware_binding(existing: object, instance: InstancePlan) -> None:
    """Read back explicit hardware choices before reusing or admitting a guest."""
    profile = instance["profile"]
    if not (profile.nic_type or profile.disk_interface or not profile.enable_secure_boot):
        return
    expected: dict[str, object] = {
        "machine_type": profile.machine_type,
        "enable_secure_boot": profile.enable_secure_boot,
    }
    if profile.nic_type:
        expected["nic_type"] = profile.nic_type
    if profile.disk_interface:
        expected["disk_interface"] = profile.disk_interface
    realized = realized_hardware(existing)
    if any(realized[key] != value for key, value in expected.items()):
        raise GCEInstanceBindingError("GCE guest hardware differs from the selected profile")


def realized_hardware(existing: object) -> dict[str, object]:
    """Read the machine type, Secure Boot, NIC, and boot disk interface that GCE reports."""
    interfaces = list(getattr(existing, "network_interfaces", None) or [])
    disks = [disk for disk in (getattr(existing, "disks", None) or []) if getattr(disk, "boot", False)]
    shielded = getattr(existing, "shielded_instance_config", None)
    return {
        "machine_type": str(getattr(existing, "machine_type", "")).rsplit("/", 1)[-1],
        "enable_secure_boot": getattr(shielded, "enable_secure_boot", None),
        # Ambiguous NIC or boot disk counts report None and never match a choice.
        "nic_type": _enum_name(interfaces[0], "nic_type") if len(interfaces) == 1 else None,
        "disk_interface": _enum_name(disks[0], "interface") if len(disks) == 1 else None,
    }


def _enum_name(item: object, key: str) -> object:
    """Accept an enum or its string name from the Compute client."""
    value = getattr(item, key, None)
    return getattr(value, "name", value)
