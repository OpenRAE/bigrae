"""Keep retained preparation and its eventual cleanup inside one immutable budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shifter_adapter_sdk.runtime import canonical_digest

from shared.operation_envelope import validate_operation_envelope
from shared.raes.operation_input import RaesInputBindings, RaesRangeIdentity, build_raes_operation_input
from shared.runtime_plugin_binding import RuntimePluginPin
from shared.runtime_plugin_preparation import RuntimePreparation

if TYPE_CHECKING:
    from engine.models import Range

_UNAVAILABLE = "Runtime preparation cleanup is unavailable"


def preparation_cleanup_payload(envelope: dict[str, Any], record: RuntimePreparation) -> dict[str, Any]:
    """Check the entire future cleanup transport before accepting any preparation."""
    source = validate_operation_envelope(envelope)
    if (source["resource"], source["operation"]) != ("raes-range", "provision"):
        raise ValueError(_UNAVAILABLE)
    original = source["payload"]
    pin = RuntimePluginPin.model_validate(original.get("runtime_plugin"))
    if record.plan_digest != canonical_digest(original.get("plan")) or record.pin_digest != pin.digest:
        raise ValueError(_UNAVAILABLE)
    payload = {**original, "runtime_preparation": record.model_dump(mode="json")}
    # Correlation UUIDs and the authority digest have fixed wire lengths for
    # the new destroy generation. The original references must all still fit.
    validate_operation_envelope({**source, "operation": "destroy", "payload": payload})
    return payload


def retained_cleanup_payload(target: Range, pin: RuntimePluginPin | None) -> dict[str, Any] | None:
    """Never rebuild accepted cleanup from a changed registry or guest selection."""
    from engine.models import OperationInput

    from ._runtime_plugin_preparation import retained_preparation

    record = retained_preparation(target, pin)
    if record is None:
        return None
    if record.state == "unprepared":
        plan = target.range_config
        if not isinstance(plan, dict):
            raise ValueError(_UNAVAILABLE)
        return build_raes_operation_input(
            plan=plan,
            bindings=RaesInputBindings(delivery=(), runtime_plugin=pin, runtime_preparation=record),
            image_candidates={},
            range_backend=target.range_backend,
            instantiation_purpose=target.instantiation_purpose or None,
            identity=RaesRangeIdentity(
                target.id, str(target.resource_generation) if target.resource_generation else None
            ),
            egress_mode=target.egress_mode,
        )
    if target.request is None or record.source_operation_id is None:
        raise ValueError(_UNAVAILABLE)
    source = OperationInput.objects.get(
        operation_id=record.source_operation_id,
        request_id=target.request.request_id,
    )
    return preparation_cleanup_payload(source.envelope, record)
