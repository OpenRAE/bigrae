"""Authorize, fence and audit tenant experiment operations without disclosing denial details."""

from __future__ import annotations

from uuid import UUID

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.credentials import CredentialContext
from shared.exceptions import CMSError
from workspaces.services import OrganizationAuthorizationError

from ._tenant_pack_authority import TenantPackAdmission, admit_tenant_pack, fence_tenant_pack

_UNAVAILABLE = "Experiment operation unavailable"


def _authorize(credential: CredentialContext, organization_uuid: UUID, operation: str) -> TenantPackAdmission:
    """Authorize the native tenant operation without disclosing denial details."""
    try:
        return admit_tenant_pack(credential, organization_uuid, operation)
    except OrganizationAuthorizationError:
        raise CMSError(_UNAVAILABLE) from None


def _fence(admission: TenantPackAdmission) -> None:
    """Recheck credential and ancestry inside the current transaction."""
    try:
        fence_tenant_pack(admission)
    except OrganizationAuthorizationError:
        raise CMSError(_UNAVAILABLE) from None


def _audit(admission: TenantPackAdmission, reference: UUID, disposition: str) -> None:
    """Record opaque operational identifiers through the strict audit boundary."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.EXPERIMENT,
            entity_id=0,
            entity_ref=str(reference),
            action=AuditAction.UPDATE,
            **principal_actor_fields(admission.credential.principal),
            new_state={"organization_uuid": str(admission.organization_uuid), "disposition": disposition},
        ),
        strict=True,
    )
