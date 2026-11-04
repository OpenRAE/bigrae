"""Closed native power addressing, without provider selection or authority."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from shared.exceptions import ValidationError

_TARGET_KEYS = frozenset({"backend", "project_id", "zone", "instance_name", "bootstrap_capability"})
_BOOTSTRAP_CAPABILITIES = frozenset({"standard", "prepromoted-domain-controller", "preconfigured-machine-host"})
MAX_NATIVE_POWER_DISKS = 128
MAX_NATIVE_POWER_FOOTPRINT_DISKS = 256


def parse_gce_resource_identity(value: object) -> str:
    """Canonicalize the provider's positive uint64 identity without coercing objects."""
    if type(value) not in (int, str):
        raise ValidationError("Native power resource identity is invalid")
    encoded = str(value)
    if not 1 <= len(encoded) <= 20 or not encoded.isascii() or not encoded.isdecimal():
        raise ValidationError("Native power resource identity is invalid")
    number = int(encoded)
    if not 0 < number < 2**64:
        raise ValidationError("Native power resource identity is invalid")
    return str(number)


@dataclass(frozen=True, slots=True)
class GcePersistentDiskIdentity:
    """One dedicated zonal disk in the target VM's project and zone."""

    name: str
    identity: str


@dataclass(frozen=True, slots=True)
class GcePowerIncarnation:
    """Observed provider identities, independent of reusable cloud resource names."""

    instance_identity: str
    disks: tuple[GcePersistentDiskIdentity, ...]

    def to_transport(self) -> dict[str, object]:
        """Return detached native evidence without raw provider responses."""
        return {
            "instance_identity": self.instance_identity,
            "disks": [{"name": disk.name, "identity": disk.identity} for disk in self.disks],
        }


def parse_gce_power_incarnation(value: object) -> GcePowerIncarnation:
    """Require a nonempty bounded footprint with distinct names and identities."""
    if not isinstance(value, dict) or set(value) != {"instance_identity", "disks"}:
        raise ValidationError("Native power incarnation shape is invalid")
    instance_identity = parse_gce_resource_identity(value["instance_identity"])
    raw = value["disks"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_NATIVE_POWER_DISKS:
        raise ValidationError("Native power disk footprint is invalid")
    disks = []
    for disk in raw:
        if not isinstance(disk, dict) or set(disk) != {"name", "identity"}:
            raise ValidationError("Native power disk shape is invalid")
        name = disk["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", name):
            raise ValidationError("Native power disk name is invalid")
        disks.append(GcePersistentDiskIdentity(name, parse_gce_resource_identity(disk["identity"])))
    if len({disk.name for disk in disks}) != len(disks) or len({disk.identity for disk in disks}) != len(disks):
        raise ValidationError("Native power disk footprint repeats a resource")
    return GcePowerIncarnation(instance_identity, tuple(sorted(disks, key=lambda disk: disk.name)))


@dataclass(frozen=True, slots=True)
class GcePowerTarget:
    """Retained GCE location; possessing this value grants no cloud access."""

    backend: str
    project_id: str
    zone: str
    instance_name: str
    bootstrap_capability: str

    def to_transport(self) -> dict[str, str]:
        """Return detached native addressing facts."""
        return asdict(self)


def parse_gce_power_target(value: object, *, instance_id: str) -> GcePowerTarget:
    """Refuse partial targets, backend changes and unbounded provider material."""
    if not isinstance(value, dict) or frozenset(value) != _TARGET_KEYS:
        raise ValidationError("Native power target shape is invalid")
    if (
        value["backend"] != "gce"
        or not isinstance(value["bootstrap_capability"], str)
        or value["bootstrap_capability"] not in _BOOTSTRAP_CAPABILITIES
    ):
        raise ValidationError("Native power target is unsupported")
    for key in ("project_id", "zone", "instance_name"):
        item = value[key]
        if not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", item):
            raise ValidationError("Native power target location is invalid")
    if value["instance_name"] != instance_id:
        raise ValidationError("Native power target instance does not match")
    return GcePowerTarget(**value)
