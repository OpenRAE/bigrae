"""Read the original admitted native call input without current inventory lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.operation_envelope import validate_operation_envelope
from shared.raes.power_input import NativePowerInput, parse_native_power_input

if TYPE_CHECKING:
    from engine.models import ParticipantPowerReservation


def retained_native_power_input(reservation: ParticipantPowerReservation) -> NativePowerInput:
    """Validate each envelope's own version and the immutable native authority."""
    from engine.models import OperationInput

    from ._launch_authority import assert_input_authority_binding

    launch = reservation.launch_intent
    stored = OperationInput.objects.get(operation_id=launch.operation_id)
    assert_input_authority_binding(stored, launch)
    envelope = validate_operation_envelope(stored.envelope)
    if (
        any(
            str(getattr(stored, key)) != str(envelope[key])
            for key in (
                "operation_id",
                "request_id",
                "resource",
                "operation",
                "contract_version",
            )
        )
        or stored.resource != "range"
        or stored.operation not in {"pause", "resume"}
        or (str(stored.request_id) != launch.payload["request_id"] or stored.operation != launch.payload["operation"])
    ):
        raise ValueError("Native call input unavailable")
    power = parse_native_power_input(
        envelope["payload"].get("native_power"),
        plan=envelope["payload"].get("range_spec"),
    )
    if power.resource_generation != reservation.compiler_binding.resource_generation:
        raise ValueError("Native call input generation changed")
    return power
