"""Installed whole-range power dispatch through exact native call permissions."""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from shared.operation_results import ResultStep
from shared.raes.power_input import NativePowerInput, parse_native_power_input

from gce_range_cell_incarnation import observe_power_incarnation
from gcp_range_cell_clients import GCEClients, _build_clients
from native_power_control_client import NativePowerControlClient
from native_power_invocation import NativePowerInvocationCallbacks, invoke_native_power_member
from provisioner_db_appends import OperationRef, append_operation_step_result
from provisioner_db_operation_input import ValidatedOperationInput, get_operation_input, get_raes_operation_input
from raes_native_power_readiness import verify_resumed_guests
from raes_plan import parse_plan

logger = logging.getLogger(__name__)


def _members(
    ref: OperationRef, verb: str, power: NativePowerInput, references: list[str], *, ready: bool = False
) -> None:
    if not references:
        return
    status = "paused" if verb == "pause" else "ready" if ready else "resuming"
    step = {
        "paused": ResultStep.RANGE_RAES_MEMBERS_PAUSED,
        "resuming": ResultStep.RANGE_RAES_MEMBERS_RESUMING,
        "ready": ResultStep.RANGE_RAES_MEMBERS_READY,
    }[status]
    append_operation_step_result(
        ref,
        resource="range",
        operation=verb,
        step=step,
        result_payload={
            "resource_generation": str(power.resource_generation),
            "members": [{"member_ref": reference, "status": status} for reference in references],
        },
    )


def _run_native_power(run: ValidatedOperationInput, verb: Literal["pause", "resume"]) -> None:
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    power: NativePowerInput | None = None
    observed: list[str] = []
    reported = False
    try:
        plan = parse_plan(run.payload["range_spec"])
        power = parse_native_power_input(run.payload.get("native_power"), plan=run.payload["range_spec"])
        original_id = UUID(run.payload["native_provisioning_operation_id"])
        original = get_raes_operation_input(
            operation_id=str(original_id),
            request_id=run.request_id,
            operation="provision",
        ).input
        if (
            original.plan != run.payload["range_spec"]
            or original.range_backend != "gce"
            or original.resource_generation != str(power.resource_generation)
        ):
            raise ValueError("Native power provisioning origin changed")
        transport = NativePowerControlClient.from_environment()
        clients = _build_clients()
        _preflight(power, clients)
        for member in power.members:
            invoke_native_power_member(
                operation_id=UUID(run.operation_id),
                verb=verb,
                power=power,
                member_ref=member.member_ref,
                clients=clients,
                callbacks=NativePowerInvocationCallbacks(
                    acquire=lambda reference, attempt: transport.acquire(UUID(run.operation_id), reference, attempt),
                    complete=transport.complete,
                    withdraw=lambda reference, attempt: transport.withdraw(UUID(run.operation_id), reference, attempt),
                ),
            )
            observed.append(member.member_ref)
        _members(ref, verb, power, observed)
        reported = True
        if verb == "resume":
            verify_resumed_guests(original, plan, power, clients)
            _members(ref, verb, power, observed, ready=True)
        append_operation_step_result(
            ref,
            resource="range",
            operation=verb,
            step=ResultStep.RANGE_TERMINAL_PAUSED if verb == "pause" else ResultStep.RANGE_TERMINAL_READY,
            result_payload={"status": "paused" if verb == "pause" else "ready"},
        )
    except Exception as exc:  # noqa: BLE001  # private SDK, guest, token and provider diagnostics stay local
        logger.error("Native range power failed operation_id=%s exc_type=%s", run.operation_id, type(exc).__name__)
        if power is not None and not reported:
            _members(ref, verb, power, observed)
        append_operation_step_result(
            ref,
            resource="range",
            operation=verb,
            step=ResultStep.RANGE_TERMINAL_FAILED,
            result_payload={"reason_code": "cloud_operation_failed", "diagnostic": "Native range power incomplete"},
        )
        raise RuntimeError("Native range power incomplete") from None


def _preflight(power: NativePowerInput, clients: GCEClients) -> None:
    """Inspect every admitted VM and disk before the first provider mutation."""
    for member in power.members:
        if observe_power_incarnation(member.target, clients=clients) != member.incarnation:
            raise ValueError("Native power resource incarnation changed")


def run_range_power(request_id: str, verb: Literal["pause", "resume"], *, operation_id: str | None = None) -> None:
    """Read the canonical input before any legacy-table path; never fall back on failure."""
    if verb not in {"pause", "resume"}:
        raise ValueError("Range power operation unavailable")
    if operation_id is not None:
        run = get_operation_input(operation_id=operation_id, request_id=request_id, resource="range", operation=verb)
        plan = run.payload.get("range_spec")
        if (isinstance(plan, dict) and plan.get("kind") == "raes_provisioning_plan") or "native_power" in run.payload:
            _run_native_power(run, verb)
            return
    from range_ops import run_range_pause, run_range_resume

    (run_range_pause if verb == "pause" else run_range_resume)(request_id, operation_id=operation_id)
