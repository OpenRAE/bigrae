"""Core-owned approval and lifetime custody of confidential adapter selections."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import transaction
from shifter_adapter_sdk.runtime import RuntimeInput, RuntimePlan, canonical_digest

from shared.field_encryption import encrypt_value
from shared.raes.runtime_preparation import validate_runtime_preparation
from shared.runtime_plugin_binding import RuntimePin, parse_runtime_pin
from shared.runtime_plugin_preparation import RuntimePreparation

if TYPE_CHECKING:
    from engine.models import Range, RuntimePluginInvocation


_IDENTITY_CHANGED = "Runtime preparation identity changed"


def preparation_result_secret(request: RuntimeInput) -> str:
    """Derive only this invocation's output key; never disclose the application key."""
    if request.phase != "prepare":
        return ""
    try:
        master = base64.urlsafe_b64decode(settings.FIELD_ENCRYPTION_KEY.encode("ascii"))
        if len(master) != 32:
            raise ValueError("Invalid field key")
        material = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"bigrae/runtime-plugin-result/v1/" + request.invocation_id.bytes,
        ).derive(master)
        return base64.urlsafe_b64encode(material).decode("ascii")
    except Exception:  # noqa: BLE001  # configuration and secret causes never cross the worker boundary
        raise ValueError("Preparation result key is unavailable") from None


def approved_preparation(
    request: RuntimeInput, result: RuntimePlan, pin: RuntimePin, plan: dict[str, Any]
) -> RuntimePreparation:
    """Admit all values before protecting the complete response with the application key."""
    result.authorize(request)
    if request.plan_digest != canonical_digest(plan):
        raise ValueError(_IDENTITY_CHANGED)
    validate_runtime_preparation(plan, result, pin)
    return RuntimePreparation(
        state="prepared",
        plan_digest=canonical_digest(plan),
        pin_digest=pin.digest,
        source_operation_id=request.operation_id,
        input_digest=request.digest,
        encrypted_result=encrypt_value(result.model_dump_json()),
    )


def approve_invocation(row: RuntimePluginInvocation, request: RuntimeInput, result: RuntimePlan) -> RuntimePreparation:
    """Read the already-authorized immutable operation; never accept a worker's plan."""
    from engine.models import OperationInput
    from shared.operation_envelope import validate_operation_envelope
    from shared.raes.operation_input import parse_raes_operation_input

    operation = OperationInput.objects.get(operation_id=row.operation_id, request_id=row.request_id)
    payload = parse_raes_operation_input(validate_operation_envelope(operation.envelope)["payload"])
    if payload.runtime_plugin is None:
        raise ValueError(_IDENTITY_CHANGED)
    record = approved_preparation(request, result, payload.runtime_plugin, payload.plan)
    from ._runtime_plugin_cleanup import preparation_cleanup_payload

    preparation_cleanup_payload(operation.envelope, record)
    return record


def preparation_identity(record: RuntimePreparation, pin: RuntimePin, plan: object) -> None:
    """Retained approval belongs to this exact original executable, input and plan."""
    if not isinstance(plan, dict) or record.pin_digest != pin.digest or record.plan_digest != canonical_digest(plan):
        raise ValueError(_IDENTITY_CHANGED)


@transaction.atomic
def retain_preparation(target: Range, record: RuntimePreparation) -> RuntimePreparation:
    """Called under the range/operation mutex; an accepted mapping cannot be replaced."""
    from engine.models import OperationInput, RuntimePluginRangeBinding
    from shared.field_encryption import decrypt_value

    from ._gcp_project_inputs import allocate_plan_projects, validate_project_preparation
    from ._runtime_plugin_cleanup import preparation_cleanup_payload

    binding = RuntimePluginRangeBinding.objects.select_for_update().get(range=target)
    if binding.pin_digest != record.pin_digest or canonical_digest(target.range_config) != record.plan_digest:
        raise ValueError(_IDENTITY_CHANGED)
    if binding.preparation is not None:
        raise ValueError("Runtime preparation is already retained")
    if (
        record.state != "prepared"
        or record.encrypted_result is None
        or record.source_operation_id is None
        or record.source_operation_id != target.provisioner_operation_id
        or target.request is None
        or not isinstance(target.range_config, dict)
    ):
        raise ValueError(_IDENTITY_CHANGED)
    pin = parse_runtime_pin(binding.pin)
    source_operation_id = record.source_operation_id
    selected = RuntimePlan.model_validate_json(decrypt_value(record.encrypted_result))
    candidate = validate_runtime_preparation(target.range_config, selected, pin)
    leases = allocate_plan_projects(target, candidate, record.plan_digest)
    validate_project_preparation(target.raes_cloud_content, target.range_config, candidate, leases, selected, pin)
    record = RuntimePreparation.model_validate({**record.model_dump(mode="json"), "cloud_projects": leases})
    source = OperationInput.objects.get(operation_id=source_operation_id, request_id=target.request.request_id)
    preparation_cleanup_payload(source.envelope, record)
    binding.preparation = record.model_dump(mode="json")
    binding.save(update_fields=["preparation"])
    return record


def retained_preparation(target: Range, pin: RuntimePin | None) -> RuntimePreparation | None:
    """Snapshot accepted values or pre-effect absence for the range's next operation."""
    from engine.models import RuntimePluginRangeBinding

    if pin is None or "provision.prepare" not in pin.manifest.capabilities:
        return None
    binding = RuntimePluginRangeBinding.objects.get(range=target)
    if binding.preparation is None:
        return RuntimePreparation(
            state="unprepared", plan_digest=canonical_digest(target.range_config), pin_digest=pin.digest
        )
    record = RuntimePreparation.model_validate(binding.preparation)
    preparation_identity(record, pin, target.range_config)
    if record.state != "prepared":
        raise ValueError("Runtime preparation is unavailable")
    return record
