"""Bind provider readback to the exact held projects and accepted native preparation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.gcp_range_projects import GcpProjectLease
from shared.gcp_runtime_types import GcpProjectWork

if TYPE_CHECKING:
    from engine.models import Range

from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

from shared.field_encryption import decrypt_value
from shared.gcp_cloud_content import open_cloud_content
from shared.gcp_runtime_plan import compile_cloud_work, native_cloud_nodes, selected_secret_payloads
from shared.raes.operation_input import RaesOperationInput, parse_raes_operation_input
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests
from shared.runtime_plugin_preparation import RuntimePreparation


def project_completion_context(
    target: Range, immutable: dict[str, Any]
) -> tuple[dict[str, Any], tuple[GcpProjectWork, ...]] | None:
    """Project proof cannot supply its own leases, original plan or selected inputs."""
    if not native_cloud_nodes(immutable["plan"]):
        return None
    from ._gcp_project_inputs import retained_project_leases

    original = parse_raes_operation_input(immutable)
    leases = retained_project_leases(target)
    if not leases:
        raise ValueError("Cloud completion has no retained custody")
    if original.range_backend != "gce" or any(lease.plan_digest != canonical_digest(original.plan) for lease in leases):
        raise ValueError("Cloud completion input binding changed")
    pin = original.runtime_plugin
    effective = original.plan
    contents = open_cloud_content(original.cloud_content, original.plan, decrypt_value)
    if pin is not None and "provision.prepare" in pin.manifest.capabilities:
        from shared.raes.runtime_preparation import validate_runtime_preparation

        result = _completion_preparation(target, original, pin, leases, original.range_backend)
        effective = validate_runtime_preparation(original.plan, result, pin)
        contents.update(selected_secret_payloads(original.plan, result, pin.manifest.provisioning_concerns))
    return effective, compile_cloud_work(effective, leases, contents)


def _completion_preparation(
    target: Range,
    original: RaesOperationInput,
    pin: RuntimePluginPin,
    leases: tuple[GcpProjectLease, ...],
    backend: str,
) -> RuntimePlan:
    """Read only the accepted preparation bound to the original source and invocation."""
    from engine.models import RuntimePluginRangeBinding

    from ._runtime_plugin_preparation import preparation_identity

    binding = RuntimePluginRangeBinding.objects.get(range=target)
    record = RuntimePreparation.model_validate(binding.preparation)
    preparation_identity(record, pin, original.plan)
    if record.state != "prepared" or record.source_operation_id is None or record.encrypted_result is None:
        raise ValueError("Cloud completion has no accepted preparation")
    if any(lease.source_operation_id != record.source_operation_id for lease in leases):
        raise ValueError("Cloud completion source changed")
    result = RuntimePlan.model_validate_json(decrypt_value(record.encrypted_result))
    request = next(
        item
        for item in runtime_plugin_requests(pin, original.plan, record.source_operation_id, target.pk, backend=backend)
        if item.phase == "prepare"
    )
    result.authorize(request)
    if record.input_digest != request.digest:
        raise ValueError("Cloud completion preparation changed")
    return result
