"""Recover the exact immutable provisioning input for a physical generation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from shared.operation_envelope import OperationEnvelopeError, validate_operation_envelope
from shared.raes.operation_input import RaesOperationInputError, parse_raes_operation_input

from ._common import EngineError

if TYPE_CHECKING:
    from engine.models import Range


def native_power_origin(row: Range) -> UUID:
    """Require one original, matching input; never reconstruct from inventory."""
    from engine.models import OperationInput

    unavailable = "Native participant provisioning origin unavailable"
    if row.request is None or row.resource_generation is None:
        raise EngineError(unavailable)
    candidates = list(
        OperationInput.objects.filter(
            request_id=row.request.request_id,
            resource="raes-range",
            operation="provision",
            envelope__payload__resource_generation=str(row.resource_generation),
        )[:2]
    )
    if len(candidates) != 1:
        raise EngineError(unavailable)
    source = candidates[0]
    try:
        envelope = validate_operation_envelope(source.envelope)
        if any(
            str(getattr(source, key)) != str(envelope[key])
            for key in ("operation_id", "request_id", "resource", "operation", "contract_version")
        ):
            raise EngineError(unavailable)
        original = parse_raes_operation_input(envelope["payload"])
        if (
            original.plan != row.range_config
            or original.resource_generation != str(row.resource_generation)
            or original.legacy_range_id != row.pk
            or original.range_backend != "gce"
        ):
            raise EngineError(unavailable)
    except (OperationEnvelopeError, RaesOperationInputError, ValueError, TypeError):
        raise EngineError(unavailable) from None
    return source.operation_id
