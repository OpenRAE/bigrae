"""Publish only a retained native range's SQL-owned parent relationship."""

from contextlib import suppress
from uuid import UUID

from django.db import transaction

from shared.authorization import HierarchyRelationshipChange
from shared.authorization.port import configured_authorization_provider

from ._range_authority import project_range_authority

_UNAVAILABLE = "Range authority publication unavailable"


def publish_range_relationships(request_id: UUID) -> None:
    """Confirm the exact creation parent outside SQL before dispatch or recovery."""
    from engine.models import Range, RangeAuthorityChange

    from ._launch_authority import range_runtime_binding_digest

    if transaction.get_connection().in_atomic_block:
        raise ValueError(_UNAVAILABLE)
    try:
        runtime = Range.objects.select_related("request").get(request__request_id=request_id)
        if runtime.scope_kind == "installation":
            return
        snapshot = project_range_authority(request_id)
        if not isinstance(snapshot.resource_generation, UUID):
            raise ValueError(_UNAVAILABLE)
        receipt = RangeAuthorityChange.objects.get(
            range=runtime,
            operation="create",
            request_uuid=request_id,
            resource_generation=snapshot.resource_generation,
            authority_resource_uuid=snapshot.public_uuid,
            authority_owner_uuid=snapshot.owner_principal_uuid,
            authority_parent_type=snapshot.parent.type,
            authority_parent_uuid=snapshot.parent.uuid,
            authority_binding_digest=range_runtime_binding_digest(runtime),
        )
        if receipt.authority_scope_kind != snapshot.scope.kind or (
            receipt.authority_account_uuid,
            receipt.authority_organization_uuid,
            receipt.authority_workspace_uuid,
        ) != (snapshot.scope.account_uuid, snapshot.scope.organization_uuid, snapshot.scope.workspace_uuid):
            raise ValueError(_UNAVAILABLE)
        change = HierarchyRelationshipChange(
            f"{snapshot.parent.type}:{snapshot.parent.uuid}", snapshot.parent.type, f"range:{snapshot.public_uuid}"
        )
        provider = configured_authorization_provider()
        with suppress(Exception):
            provider.write_relationships(change)
        if not provider.read_relationships(change).grant_present or project_range_authority(request_id) != snapshot:
            raise ValueError(_UNAVAILABLE)
    except Exception:  # noqa: BLE001  # provider errors can contain credentials; expose only a bounded failure
        raise ValueError(_UNAVAILABLE) from None
