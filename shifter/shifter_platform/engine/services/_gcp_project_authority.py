"""Installation authority for registered GCP range-project operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.authorization import AuthorizationRequest, TargetRef
from shared.authorization.policy import require_authorization
from shared.credentials import CredentialContext, resolve_current_credential
from shared.identity_scope import ResourceScope
from shared.operation_authority import credential_reference_fields
from shared.operation_envelope import canonical_payload_digest

if TYPE_CHECKING:
    from engine.models import GcpRangeProject

_DENIED = "Project administration is not permitted"


_ACTION = "installation.manage_cloud_authority"


def require_project_administrator(credential: CredentialContext) -> CredentialContext:
    """Staff flags and scenario documents cannot grant installation authority."""
    try:
        current = resolve_current_credential(credential)
        require_authorization(
            AuthorizationRequest(
                current.principal, _ACTION, TargetRef("installation"), ResourceScope("installation"), current.ceiling
            )
        )
        return current
    except Exception:  # noqa: BLE001  # current policy/proof failures are one bounded denial
        raise PermissionError(_DENIED) from None


def project_authority_fields(current: CredentialContext, row: GcpRangeProject) -> dict[str, object]:
    """Bind one original credential to the immutable operator assignment."""
    return {
        **credential_reference_fields(current),
        "authority_kind": "principal",
        "authority_action": _ACTION,
        "authority_target_type": "installation",
        "authority_target_uuid": None,
        "authority_parent_type": "installation",
        "authority_parent_uuid": None,
        "authority_scope_kind": "installation",
        "authority_account_uuid": None,
        "authority_organization_uuid": None,
        "authority_workspace_uuid": None,
        "authority_owner_uuid": current.principal.uuid,
        "authority_resource_uuid": row.pk,
        "authority_binding_digest": canonical_payload_digest(
            {"id": str(row.pk), "organization_uuid": str(row.organization_uuid), "project_id": row.project_id}
        ),
    }
