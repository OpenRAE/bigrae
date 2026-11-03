"""Closed private host-management capability and result projection."""

from typing import Any

from shared.raes.image_policy import validate_management_ssh_port, validate_management_ssh_username


def validate_management_targets(value: object, plan: dict[str, Any]) -> tuple[str, ...]:
    """Select unique single-guest targets from the admitted plan."""
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise ValueError("Management targets are invalid")
    resources = plan.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("Management plan is invalid")
    targets = []
    for target in value:
        resource = resources.get(target) if isinstance(target, str) else None
        if (
            not isinstance(resource, dict)
            or resource.get("resource_type") != "node"
            or resource.get("payload", {}).get("count", 1) != 1
        ):
            raise ValueError("Management target requires one admitted guest")
        targets.append(target)
    if len(set(targets)) != len(targets):
        raise ValueError("Management targets are not unique")
    return tuple(targets)


def validate_management_access(value: object) -> dict[str, dict[str, Any]]:
    """Validate the closed private management-reference projection."""
    if not isinstance(value, dict) or len(value) > 64:
        raise ValueError("Management projection is invalid")
    result = {}
    for target, access in value.items():
        if (
            not isinstance(target, str)
            or not 1 <= len(target) <= 1024
            or not isinstance(access, dict)
            or set(access) != {"ssh_key_secret_ref", "host_public_key", "username", "port"}
        ):
            raise ValueError("Management projection is invalid")
        for key, limit in (("ssh_key_secret_ref", 1024), ("host_public_key", 16384), ("username", 32)):
            if not isinstance(access[key], str) or not access[key].strip() or len(access[key]) > limit:
                raise ValueError("Management projection is invalid")
        validate_management_ssh_port(access["port"])
        validate_management_ssh_username(access["username"])
        result[target] = dict(access)
    return result
