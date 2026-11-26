"""Keep retained preparation and its eventual cleanup inside one immutable budget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shifter_adapter_sdk.runtime import canonical_digest

from shared.operation_envelope import validate_operation_envelope
from shared.runtime_plugin_binding import parse_runtime_pin
from shared.runtime_plugin_preparation import RuntimePreparation

if TYPE_CHECKING:
    pass

_UNAVAILABLE = "Runtime preparation cleanup is unavailable"


def preparation_cleanup_payload(envelope: dict[str, Any], record: RuntimePreparation) -> dict[str, Any]:
    """Check the entire future cleanup transport before accepting any preparation."""
    source = validate_operation_envelope(envelope)
    if (source["resource"], source["operation"]) != ("raes-range", "provision"):
        raise ValueError(_UNAVAILABLE)
    original = source["payload"]
    pin = parse_runtime_pin(original.get("runtime_plugin"))
    if record.plan_digest != canonical_digest(original.get("plan")) or record.pin_digest != pin.digest:
        raise ValueError(_UNAVAILABLE)
    payload = {**original, "runtime_preparation": record.model_dump(mode="json")}
    if record.cloud_projects:
        payload["gcp_projects"] = [lease.model_dump(mode="json") for lease in record.cloud_projects]
    # Correlation UUIDs and the authority digest have fixed wire lengths for
    # the new destroy generation. The original references must all still fit.
    validate_operation_envelope({**source, "operation": "destroy", "payload": payload})
    return payload
