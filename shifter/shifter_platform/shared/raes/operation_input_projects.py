"""Closed registered-project references beside the original native RAES plan."""

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter
from shifter_adapter_sdk.runtime import canonical_digest

from shared.gcp_cloud_content import CloudContentEnvelope
from shared.gcp_range_projects import MAX_PROJECTS_PER_RANGE, GcpProjectLease
from shared.raes.operation_input_identity import RaesOperationInputError
from shared.runtime_plugin_preparation import RuntimePreparation


def cloud_content_binding(obj: Mapping[str, Any]) -> CloudContentEnvelope | None:
    """Admit only the sealed payload bound to the exact original native plan."""
    if "cloud_content" not in obj:
        return None
    try:
        content = CloudContentEnvelope.model_validate(obj["cloud_content"])
        if content.plan_digest != canonical_digest(obj["plan"]):
            raise ValueError()
        return content
    except (ValueError, KeyError):
        raise RaesOperationInputError("raes cloud content binding is invalid") from None


def project_bindings(obj: Mapping[str, Any], preparation: RuntimePreparation | None) -> tuple[GcpProjectLease, ...]:
    """A sidecar cannot transplant a project use to another plan or naming identity."""
    try:
        rows = obj.get("gcp_projects", [])
        if not isinstance(rows, list) or len(rows) > MAX_PROJECTS_PER_RANGE:
            raise ValueError("Invalid project references")
        leases = tuple(TypeAdapter(list[GcpProjectLease]).validate_python(rows))
        if leases and obj["range_backend"] != "gce":
            raise ValueError("Invalid project backend")
        if len({lease.lease_id for lease in leases}) != len(leases) or len(
            {lease.project_id for lease in leases}
        ) != len(leases):
            raise ValueError("Duplicate project references")
        _validate_lease_identity(leases, obj)
        if preparation is not None and preparation.cloud_projects != leases:
            raise ValueError("Preparation project references changed")
        return leases
    except (ValueError, KeyError):
        raise RaesOperationInputError("raes operation input project binding is invalid") from None


def _validate_lease_identity(leases: tuple[GcpProjectLease, ...], obj: Mapping[str, Any]) -> None:
    """All leases must retain one original custody identity and the exact plan and range."""
    identities = {
        (lease.source_operation_id, lease.request_id, lease.range_uuid, lease.organization_uuid) for lease in leases
    }
    if len(identities) > 1:
        raise ValueError("Project custody identity changed")
    digest = canonical_digest(obj["plan"])
    if any(lease.range_id != obj["legacy_range_id"] or lease.plan_digest != digest for lease in leases):
        raise ValueError("Project reference identity changed")
