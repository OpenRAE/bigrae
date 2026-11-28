"""Creation-origin authority for a native range generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from engine.models import ProvisionerLaunchIntent, RangeAuthorityChange
from engine.services._range.binding_digest import range_runtime_binding_digest
from shared.operation_authority import credential_reference_fields

if TYPE_CHECKING:
    from engine.models import Range
    from shared.credentials import CredentialContext

_RANGE_CREATION_AUTHORITY_UNAVAILABLE = "Range creation authority unavailable"


def _installation_creation_authority(credential: CredentialContext, runtime: Range) -> dict[str, object]:
    """Bind an admitted installation-owned warm preparation to its exact runtime."""

    if runtime.cms_range_uuid is None or runtime.owner_principal_uuid != credential.principal.uuid:
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    return {
        **credential_reference_fields(credential),
        "authority_kind": "warm_pool",
        "authority_action": "installation.launch_range",
        "authority_target_type": "installation",
        "authority_target_uuid": None,
        "authority_parent_type": "installation",
        "authority_parent_uuid": None,
        "authority_scope_kind": "installation",
        "authority_account_uuid": None,
        "authority_organization_uuid": None,
        "authority_workspace_uuid": None,
        "authority_owner_uuid": credential.principal.uuid,
        "authority_resource_uuid": runtime.cms_range_uuid,
        "authority_binding_digest": range_runtime_binding_digest(runtime),
    }


def _assert_creation_origin(runtime: Range, credential: CredentialContext) -> None:
    """The native generation's creation receipt owns its original exact proof."""

    expected = credential_reference_fields(credential)
    if runtime.scope_kind in {"account", "installation"} and runtime.owner_principal_uuid is not None:
        _assert_native_creation_receipt(runtime, expected)
    originals = ProvisionerLaunchIntent.objects.filter(
        authority_resource_uuid=runtime.cms_range_uuid, payload__operation="provision"
    )
    if any(any(getattr(original, key) != value for key, value in expected.items()) for original in originals):
        raise ValueError("Range initiating authority conflict")


def _assert_native_creation_receipt(runtime: Range, expected: Mapping[str, object]) -> None:
    """Require the unique exact-generation receipt, including warm custody binding."""

    if runtime.request is None or runtime.resource_generation is None:
        raise ValueError("Range creation origin authority conflict")
    receipts = list(
        RangeAuthorityChange.objects.filter(
            range=runtime,
            operation="create",
            resource_generation=runtime.resource_generation,
            request_uuid=runtime.request.request_id,
            authority_resource_uuid=runtime.cms_range_uuid,
        )[:2]
    )
    if len(receipts) != 1 or any(getattr(receipts[0], key) != value for key, value in expected.items()):
        raise ValueError("Range creation origin authority conflict")
    if runtime.scope_kind == "installation" and (
        receipts[0].authority_kind != "warm_pool"
        or receipts[0].authority_binding_digest != range_runtime_binding_digest(runtime)
    ):
        raise ValueError("Warm creation custody changed")
