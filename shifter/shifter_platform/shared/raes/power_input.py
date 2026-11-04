"""Bounded native power input beside the retained provisioning plan.

This is native resource addressing. It is not portable control state, an
executable provider binding, a current authorization, or an execution permit.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shared.exceptions import ValidationError
from shared.native_power import (
    MAX_NATIVE_POWER_FOOTPRINT_DISKS,
    GcePowerIncarnation,
    GcePowerTarget,
    parse_gce_power_incarnation,
    parse_gce_power_target,
)
from shared.operation_result_payloads import MAX_RAES_MEMBERS

NATIVE_POWER_INPUT_VERSION = "shifter-native-power/v1"


@dataclass(frozen=True, slots=True)
class NativePowerMember:
    """One exact compiled member and its detached realized cloud target."""

    member_ref: str
    target: GcePowerTarget
    incarnation: GcePowerIncarnation


@dataclass(frozen=True, slots=True)
class NativePowerInput:
    """Exact resource incarnation and complete member addressing."""

    resource_generation: UUID
    members: tuple[NativePowerMember, ...]


def _planned_node_members(address: object, resource: object) -> frozenset[str]:
    """Validate one published node count without interpreting provisioning intent."""
    if not isinstance(resource, dict):
        raise ValidationError("Native power plan membership is invalid")
    if resource.get("resource_type") != "node":
        return frozenset()
    if not isinstance(address, str) or resource.get("address") != address or not 1 <= len(address) <= 500:
        raise ValidationError("Native power plan membership is invalid")
    payload = resource.get("payload")
    if not isinstance(payload, dict):
        raise ValidationError("Native power plan membership is invalid")
    count = payload.get("count")
    count = 1 if count is None else count
    if type(count) is not int or not 1 <= count <= MAX_RAES_MEMBERS:
        raise ValidationError("Native power plan membership is invalid")
    return frozenset(f"{address}#{index}" for index in range(count))


def planned_member_references(plan: object) -> frozenset[str]:
    """Select node membership using the serialized plan's published count field.

    Full plan interpretation still belongs to the provisioner. This selection
    must not replace it or reconstruct image, guest or controller semantics.
    """
    if not isinstance(plan, dict) or plan.get("kind") != "raes_provisioning_plan":
        raise ValidationError("Native power requires a compiled provisioning plan")
    resources = plan.get("resources")
    if not isinstance(resources, dict) or len(resources) > 4096:
        raise ValidationError("Native power plan membership is invalid")
    members: set[str] = set()
    for address, resource in resources.items():
        members.update(_planned_node_members(address, resource))
        if len(members) > MAX_RAES_MEMBERS:
            raise ValidationError("Native power footprint is too large")
    if not members:
        raise ValidationError("Native power footprint is empty")
    return frozenset(members)


def _parse_power_member(entry: object, expected: frozenset[str]) -> NativePowerMember:
    """Parse one closed member before whole-footprint identity admission."""
    if not isinstance(entry, dict) or set(entry) != {"member_ref", "target", "incarnation"}:
        raise ValidationError("Native power member shape is invalid")
    ref = entry["member_ref"]
    if not isinstance(ref, str) or ref not in expected:
        raise ValidationError("Native power member does not match the compiled footprint")
    raw_target = entry["target"]
    if not isinstance(raw_target, dict):
        raise ValidationError("Native power target shape is invalid")
    target = parse_gce_power_target(raw_target, instance_id=raw_target.get("instance_name", ""))
    if target.bootstrap_capability != "standard":
        raise ValidationError("Native power target is unsupported or duplicated")
    return NativePowerMember(ref, target, parse_gce_power_incarnation(entry["incarnation"]))


def _register_footprint(
    member: NativePowerMember,
    instance_identities: set[tuple[str, str, str]],
    disk_names: set[tuple[str, str, str]],
    disk_identities: set[tuple[str, str, str]],
) -> None:
    """Exclude shared or duplicated VM and persistent disk identities across members."""
    target, incarnation = member.target, member.incarnation
    instance_key = target.project_id, target.zone, incarnation.instance_identity
    if instance_key in instance_identities:
        raise ValidationError("Native power footprint repeats an instance identity")
    instance_identities.add(instance_key)
    for disk in incarnation.disks:
        name_key = target.project_id, target.zone, disk.name
        identity_key = target.project_id, target.zone, disk.identity
        if name_key in disk_names or identity_key in disk_identities:
            raise ValidationError("Native power footprint repeats a persistent disk")
        disk_names.add(name_key)
        disk_identities.add(identity_key)
    if len(disk_names) > MAX_NATIVE_POWER_FOOTPRINT_DISKS:
        raise ValidationError("Native power disk footprint is too large")


def parse_native_power_input(value: object, *, plan: object) -> NativePowerInput:
    """Refuse incomplete, duplicated, foreign or unsupported power addressing."""
    if not isinstance(value, dict) or set(value) != {"contract_version", "resource_generation", "members"}:
        raise ValidationError("Native power input shape is invalid")
    if value["contract_version"] != NATIVE_POWER_INPUT_VERSION:
        raise ValidationError("Native power input version is unsupported")
    try:
        generation = UUID(value["resource_generation"])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Native power resource generation is unavailable") from None
    raw = value["members"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_RAES_MEMBERS:
        raise ValidationError("Native power footprint is invalid")
    expected = planned_member_references(plan)
    members = []
    references: set[str] = set()
    targets: set[GcePowerTarget] = set()
    instance_identities: set[tuple[str, str, str]] = set()
    disk_names: set[tuple[str, str, str]] = set()
    disk_identities: set[tuple[str, str, str]] = set()
    for entry in raw:
        member = _parse_power_member(entry, expected)
        ref, target, incarnation = member.member_ref, member.target, member.incarnation
        if ref in references or target in targets:
            raise ValidationError("Native power target is unsupported or duplicated")
        _register_footprint(member, instance_identities, disk_names, disk_identities)
        references.add(ref)
        targets.add(target)
        members.append(NativePowerMember(ref, target, incarnation))
    if references != expected:
        raise ValidationError("Native power footprint is incomplete")
    return NativePowerInput(generation, tuple(members))


def build_native_power_input(
    plan: object,
    realized: object,
    resource_generation: UUID | None,
    *,
    backend: str,
) -> dict[str, object]:
    """Project only retained targets; never derive them from deployment defaults."""
    if backend != "gce" or not isinstance(realized, list) or not 1 <= len(realized) <= MAX_RAES_MEMBERS:
        raise ValidationError("Native power backend is unsupported")
    members = []
    for member in realized:
        if not isinstance(member, dict):
            raise ValidationError("Native power realization is invalid")
        target = parse_gce_power_target(member.get("native_power_target"), instance_id=member.get("instance_id", ""))
        incarnation = parse_gce_power_incarnation(member.get("native_power_incarnation"))
        members.append(
            {
                "member_ref": member.get("uuid"),
                "target": target.to_transport(),
                "incarnation": incarnation.to_transport(),
            }
        )
    value: dict[str, object] = {
        "contract_version": NATIVE_POWER_INPUT_VERSION,
        "resource_generation": str(resource_generation) if resource_generation is not None else None,
        "members": members,
    }
    parse_native_power_input(value, plan=plan)
    return value
