"""Canonical provisioner launch commands and their versioned payloads.

The parser and codec are pure. Launch admission, enqueue, dispatch, and the
per-resource services all reconstruct commands through this module.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

WORKER_TRIAL_RESOURCE = "worker-trial"
WORKER_TRIAL_OPERATIONS = frozenset({"run", "collect"})
WORKER_TRIAL_UNAVAILABLE = "Worker trial operation unavailable"

_OPERATIONS = {
    "range-project": {"register", "verify"},
    "range": {"provision", "destroy", "pause", "resume"},
    # ``activate`` (#28) hands an atomically claimed warm generation to its
    # claimant. Only the ownership-neutral raes-range path carries it; the legacy
    # user_id-bearing ``range`` path is warm-ineligible (preflight #28).
    "raes-range": {"provision", "destroy", "pause", "resume", "activate"},
    "ngfw": {"provision", "deprovision", "start", "stop"},
}


def _request_payload(command: list[str]) -> dict[str, object] | None:
    """Validate and normalize a request-id command when its shape matches."""
    if len(command) != 4 or command[2] != "--request-id":
        return None
    resource, operation, _, request_id = command
    if resource not in _OPERATIONS or operation not in _OPERATIONS[resource]:
        raise ValueError("unsupported provisioner resource or operation")
    try:
        parsed_request_id = UUID(request_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("request_id must be a UUID") from exc
    return {
        "version": 1,
        "resource": resource,
        "operation": operation,
        "request_id": str(parsed_request_id),
    }


def _legacy_range_payload(command: list[str]) -> dict[str, object] | None:
    """Validate and normalize a legacy range command when its shape matches."""
    if len(command) != 6 or command[:2] not in (["range", "provision"], ["range", "destroy"]):
        return None
    if command[2] != "--range-id" or command[4] != "--user-id":
        raise ValueError("legacy range command must use canonical identifier flags")
    try:
        range_id, user_id = int(command[3]), int(command[5])
    except ValueError as exc:
        raise ValueError("legacy identifiers must be integers") from exc
    if range_id < 0 or user_id < 0:
        raise ValueError("legacy identifiers must be non-negative")
    return {
        "version": 1,
        "resource": "range",
        "operation": command[1],
        "range_id": range_id,
        "user_id": user_id,
    }


def _split_operation_id(command: list[str]) -> tuple[list[str], str | None]:
    """Split an optional trailing ``--operation-id <uuid>`` correlation pair.

    The generation fence (``operation_id``) is carried on the launched argv so the
    provisioner tags its input read and result appends with exactly the operation
    it is executing, never "latest by request" (ADR-043). It is optional so the
    engine can validate the canonical command before the id is minted, and add it
    only when reconstructing the dispatch argv from a persisted intent.
    """
    if len(command) >= 2 and command[-2] == "--operation-id":
        try:
            operation_id = str(UUID(command[-1]))
        except (TypeError, ValueError) as exc:
            raise ValueError("operation_id must be a UUID") from exc
        return command[:-2], operation_id
    return command, None


def validate_provisioner_command(command: list[str]) -> dict[str, object]:
    """Return a versioned, secret-free payload for one canonical CLI command."""
    if not isinstance(command, list) or any(not isinstance(part, str) for part in command):
        raise ValueError("provisioner command must be a list of strings")
    base, operation_id = _split_operation_id(command)
    payload: dict[str, object] | None
    if base[:1] == ["vpn-profile"]:
        payload = validate_vpn_command(base)
    elif base[:1] == ["worker-trial"]:
        payload = validate_worker_trial_command(base)
    else:
        payload = _request_payload(base) or _legacy_range_payload(base)
    if payload is None:
        raise ValueError("command does not match a canonical provisioner launch shape")
    if operation_id is not None:
        payload["operation_id"] = operation_id
    return payload


def command_from_payload(payload: dict[str, object]) -> list[str]:
    """Reconstruct and revalidate the canonical command at the trust boundary."""
    if payload.get("version") != 1:
        raise ValueError("unsupported provisioner launch intent version")
    resource = payload.get("resource")
    operation = payload.get("operation")
    if "request_id" in payload:
        command = [str(resource), str(operation), "--request-id", str(payload["request_id"])]
        if resource == "vpn-profile":
            command.extend(["--profile-id", str(payload["profile_id"])])
        elif resource == "worker-trial":
            command.extend(["--trial-id", str(payload["trial_id"])])
    else:
        command = [
            str(resource),
            str(operation),
            "--range-id",
            str(payload.get("range_id")),
            "--user-id",
            str(payload.get("user_id")),
        ]
    if payload.get("operation_id"):
        command = [*command, "--operation-id", str(payload["operation_id"])]
    if validate_provisioner_command(command) != payload:
        raise ValueError("provisioner launch intent payload is not canonical")
    return command


def validate_vpn_command(command: list[str]) -> dict[str, Any]:
    """Parse only the supported native PKI command and canonical identifiers."""
    if (
        len(command) != 6
        or command[0] != "vpn-profile"
        or command[1] not in {"issue", "revoke", "refresh-crl", "purge"}
        or command[2] != "--request-id"
        or command[4] != "--profile-id"
    ):
        raise ValueError("VPN operation unavailable")
    return {
        "version": 1,
        "resource": "vpn-profile",
        "operation": command[1],
        "request_id": str(UUID(command[3])),
        "profile_id": str(UUID(command[5])),
    }


def validate_worker_trial_command(command: list[str]) -> dict[str, Any]:
    """Parse only the canonical ``worker-trial`` command."""
    if (
        len(command) != 6
        or command[0] != WORKER_TRIAL_RESOURCE
        or command[1] not in WORKER_TRIAL_OPERATIONS
        or command[2] != "--request-id"
        or command[4] != "--trial-id"
    ):
        raise ValueError(WORKER_TRIAL_UNAVAILABLE)
    return {
        "version": 1,
        "resource": WORKER_TRIAL_RESOURCE,
        "operation": command[1],
        "request_id": str(UUID(command[3])),
        "trial_id": str(UUID(command[5])),
    }
