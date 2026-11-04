"""Bounded RAES range-member result projection."""

from __future__ import annotations

from raes_gcp_network_allocation import RaesRealizationError


def realized_members(apply_result: dict[str, object]) -> list[dict[str, object]]:
    """Project realized instances into the bounded member/access result (#1710)."""
    instances = apply_result.get("instances")
    if not isinstance(instances, list):
        raise RaesRealizationError("realized instance outputs are invalid")
    members: list[dict[str, object]] = []
    for instance in instances:
        if not isinstance(instance, dict):
            raise RaesRealizationError("realized instance outputs are invalid")
        members.append(_realized_member(instance))
    return members


def _realized_member(instance: dict[str, object]) -> dict[str, object]:
    """Project one provider instance without credential values or raw responses."""
    raw_channels = instance.get("participant_access_channels")
    channels = list(raw_channels) if isinstance(raw_channels, list) else []
    raw_usernames = instance.get("participant_access_usernames")
    usernames = dict(raw_usernames) if isinstance(raw_usernames, dict) else {}
    member: dict[str, object] = {
        "uuid": str(instance.get("uuid", "")),
        "name": str(instance.get("name", "")),
        "os_type": str(instance.get("os", "")),
        "private_ip": str(instance.get("private_ip", "")),
        "instance_id": str(instance.get("instance_id", "")),
        "subnet_name": str(instance.get("subnet_name", "")),
        "participant_access_channels": channels,
        "participant_access_usernames": usernames,
    }
    host_key = str(
        instance.get("participant_ssh_host_public_key")
        or instance.get("host_public_key")
        or instance.get("gcp_host_public_key", "")
    )
    if host_key:
        member["host_public_key"] = host_key
    _copy_optional_text(member, instance, "sftp_root_directory", "sftp_root_directory")
    for channel, key in (("ssh", "ssh_key_secret_arn"), ("rdp", "rdp_password_secret_arn")):
        if channel in channels:
            member[key] = str(instance.get(key, ""))
    return member


def _copy_optional_text(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    """Copy one bounded optional text field when it is non-empty."""
    value = str(source.get(source_key, ""))
    if value:
        target[target_key] = value


def realized_management(apply_result: dict[str, object], targets: tuple[str, ...]) -> dict[str, dict[str, object]]:
    """Project only the host access explicitly admitted by immutable input."""
    from shared.range_management import validate_management_access

    if not targets:
        return {}
    expected = {f"{target}#0" for target in targets}
    result = {}
    instances = apply_result.get("instances", [])
    if not isinstance(instances, list) or any(not isinstance(item, dict) for item in instances):
        raise RaesRealizationError("private management membership is invalid")
    for instance in instances:
        if instance.get("uuid") not in expected:
            continue
        result[instance["uuid"]] = {
            "ssh_key_secret_ref": instance.get("gcp_host_ssh_key_secret_ref", ""),
            "host_public_key": instance.get("gcp_host_public_key", ""),
            "username": instance.get("gcp_host_ssh_username", ""),
            "port": instance.get("gcp_host_ssh_port", 22),
        }
    if set(result) != expected:
        raise RaesRealizationError("admitted private management targets are missing")
    return validate_management_access(result)


def management_fragment(apply_result: dict[str, object], targets: tuple[str, ...]) -> dict[str, object]:
    """Emit a private result fragment only for explicitly admitted management targets."""
    management = realized_management(apply_result, targets)
    return {"management_access": management} if management else {}
