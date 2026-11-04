"""Closed native member invocation through the incumbent GCE power boundary.

Installation code supplies the authenticated owner transport. No scenario,
caller, environment variable or response can install executable provider code.
The owner consumes one permission after read-only preflight; uncertainty stays
with that permission rather than being retried into a second cloud call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from shared.native_participant import NativePowerInvocationGrant, native_power_invocation_id
from shared.raes.power_input import NativePowerInput

from gce_range_cell_power import run_power_operation
from gcp_range_cell_clients import GCEClients

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NativePowerInvocationCallbacks:
    """Installed transport callbacks for the original acquire, completion, and no-call attempt."""

    acquire: Callable[[str, UUID], NativePowerInvocationGrant]
    complete: Callable[[UUID, UUID], None]
    withdraw: Callable[[str, UUID], None]


def invoke_native_power_member(
    *,
    operation_id: UUID,
    verb: Literal["pause", "resume"],
    power: NativePowerInput,
    member_ref: str,
    callbacks: NativePowerInvocationCallbacks,
    clients: GCEClients | None = None,
) -> None:
    """Validate exact permission immediately before one start/stop call.

    Successful return means the provider helper observed this member's power
    postcondition and retained incarnation. Range and access readiness still
    belong to the existing result and qualification owners.
    """
    if verb not in {"pause", "resume"}:
        raise ValueError("Native power operation unavailable")
    members = [member for member in power.members if member.member_ref == member_ref]
    if len(members) != 1:
        raise ValueError("Native power member unavailable")
    member = members[0]
    expected = NativePowerInvocationGrant(
        invocation_id=native_power_invocation_id(operation_id, member_ref),
        operation_id=operation_id,
        resource_generation=power.resource_generation,
        verb=verb,
        member_ref=member_ref,
        target=member.target,
        incarnation=member.incarnation,
        attempt_id=uuid4(),
    )

    def before_invoke() -> None:
        try:
            grant = callbacks.acquire(member_ref, expected.attempt_id)
            if not isinstance(grant, NativePowerInvocationGrant) or grant != expected:
                raise ValueError
        except Exception:  # noqa: BLE001  # this helper has not reached the provider call
            try:
                callbacks.withdraw(member_ref, expected.attempt_id)
            except Exception as exc:  # noqa: BLE001  # a failed withdrawal conservatively retains exclusion
                logger.warning("Native pre-call withdrawal unavailable exc_type=%s", type(exc).__name__)
            raise ValueError("Native power invocation permission unavailable") from None

    run_power_operation(
        "stop" if verb == "pause" else "start",
        {
            "gcp_project_id": member.target.project_id,
            "gcp_zone": member.target.zone,
            "gcp_instance_name": member.target.instance_name,
            "native_power_target": member.target.to_transport(),
        },
        clients=clients,
        expected_incarnation=member.incarnation,
        before_invoke=before_invoke,
        invocation_id=expected.invocation_id,
    )
    callbacks.complete(expected.invocation_id, expected.attempt_id)
