"""Local credential, ancestry and generation fences for admitted Engine launches."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from engine.models import Instance
from engine.worker_retention import fence_worker_retirement
from shared.credentials import resolve_local_credential
from shared.operation_authority import authority_resource_scope, credential_reference_from_fields
from shared.range_workspace_aggregate import require_range_event_association
from workspaces.services import resource_scope_from_ids

from ._device_authority import assert_device_authority_binding, assert_device_cleanup_origin
from ._launch_cleanup_authority import assert_cleanup_origin
from ._runtime_binding_digest import range_runtime_binding_digest as range_runtime_binding_digest

if TYPE_CHECKING:
    from engine.models import ProvisionerLaunchIntent, Range

_OPERATION_AUTHORITY_UNAVAILABLE = "Operation authority unavailable"


def assert_launch_authority_binding(intent: ProvisionerLaunchIntent, runtime: Range | Instance) -> None:
    """Pure SQL-fact fence after policy evaluation, safe inside a row lock."""

    if isinstance(runtime, Instance):
        assert_device_authority_binding(intent, runtime)
        return
    if intent.authority_kind not in {"principal", "cleanup", "warm_pool"} or (
        intent.authority_binding_digest != range_runtime_binding_digest(runtime)
    ):
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
    if intent.payload.get("operation") in {"destroy", "cancel", "pause", "resume"}:
        fence_worker_retirement(runtime)
    if intent.authority_kind == "cleanup":
        assert_cleanup_origin(intent, runtime)


def assert_admitted_launch_binding(fields: dict[str, object], runtime: Range | Instance) -> None:
    """Fence scope/owner/backend drift after admission and before durable commit."""
    if fields.get("authority_kind") in {"principal", "warm_pool"}:
        admitted = credential_reference_from_fields(fields)
        if resolve_local_credential(admitted) != admitted:
            raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
    if fields and fields["authority_binding_digest"] != range_runtime_binding_digest(runtime):
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)

    if isinstance(runtime, Instance):
        _assert_admitted_device_binding(fields, runtime)
        return
    if fields.get("authority_kind") == "principal":
        _assert_admitted_range_scope(fields, runtime)
    if fields.get("authority_kind") == "warm_pool":
        _assert_admitted_warm_binding(fields, runtime)


def _assert_admitted_warm_binding(fields: dict[str, object], runtime: Range) -> None:
    """Fence exact warm-generation custody under the caller's existing row lock."""
    if (
        runtime.scope_kind != "installation"
        or runtime.owner_principal_uuid != fields.get("authority_owner_uuid")
        or runtime.cms_range_uuid != fields.get("authority_resource_uuid")
    ):
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)


def _assert_admitted_range_scope(fields: dict[str, object], runtime: Range) -> None:
    """Keep exact native ancestry and the deferred CTF association at commit."""

    scope = authority_resource_scope(fields)
    runtime_scope = resource_scope_from_ids(
        kind=runtime.scope_kind,
        account_id=runtime.account_id,
        organization_id=runtime.organization_id,
        workspace_id=runtime.workspace_id,
    )
    if runtime.cms_range_uuid != fields.get("authority_resource_uuid") or runtime_scope != scope:
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
    # Creation waits for the CTF aggregate's exact participant, spare or recovery
    # association. Dispatch rechecks this same binding.
    event_parent = fields.get("authority_parent_uuid") if fields.get("authority_parent_type") == "event" else None
    if event_parent is None:
        return
    if runtime.event_uuid != event_parent or runtime.request is None or not isinstance(event_parent, UUID):
        raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)

    require_range_event_association(runtime.request.request_id, event_parent)


def _assert_admitted_device_binding(fields: dict[str, object], runtime: Instance) -> None:
    """Require original principal proof or verified native device cleanup."""
    if runtime.request is None:
        raise PermissionError("Device authority unavailable")
    if runtime.request.owner_principal_uuid is not None and not fields:
        raise PermissionError("Device authority unavailable")
    if fields.get("authority_kind") == "cleanup":
        origin = fields["cleanup_origin_operation_uuid"]
        if not isinstance(origin, UUID):
            raise ValueError("Device cleanup origin unavailable")
        assert_device_cleanup_origin(origin, runtime)
