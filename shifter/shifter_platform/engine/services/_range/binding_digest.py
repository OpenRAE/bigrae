"""Digest of the native resource, owner, scope, and backend facts that authority binds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import Instance
from engine.services._device_authority import device_binding_digest
from shared.operation_envelope import canonical_payload_digest

if TYPE_CHECKING:
    from engine.models import Range

_OPERATION_AUTHORITY_UNAVAILABLE = "Operation authority unavailable"


def range_runtime_binding_digest(row: Range | Instance) -> str:
    """Pin native resource/owner/scope/backend facts, including for cleanup."""

    if isinstance(row, Instance):
        return device_binding_digest(row)
    if row.request is None:
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
    return canonical_payload_digest(
        {
            "native_uuid": str(row.uuid),
            "public_uuid": str(row.cms_range_uuid),
            "request_uuid": str(row.request.request_id),
            "owner_uuid": str(row.owner_principal_uuid),
            "scope_kind": row.scope_kind,
            "account_id": row.account_id,
            "organization_id": row.organization_id,
            "workspace_id": row.workspace_id,
            "event_uuid": str(row.event_uuid),
            "range_backend": row.range_backend,
            "resource_generation": str(row.resource_generation),
        }
    )
