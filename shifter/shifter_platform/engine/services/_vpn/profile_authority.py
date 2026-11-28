"""Live application authority and runtime fences for one individual VPN certificate."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.utils import timezone

from engine.models import Range
from engine.services._range.authority import project_range_authority
from engine.services._range.binding_digest import range_runtime_binding_digest
from engine.services._vpn.destinations import _member_destinations
from shared.authorization import AuthorizationRequest, TargetRef
from shared.authorization.policy import require_authorization
from shared.credentials import CredentialContext, resolve_credential_scope, resolve_current_credential
from shared.operation_authority import credential_reference_fields, credential_reference_from_record
from shared.principal_port import resolve_principal
from shared.range_workspace_aggregate import require_range_vpn_participation
from shared.remote_access import parse_openvpn_capability

if TYPE_CHECKING:
    from engine.models import VpnAccessProfile
    from engine.services._vpn.destinations import VpnDestination

_VPN_PROFILE_UNAVAILABLE = "VPN profile unavailable"


def _resolve_profile_credential(credential: CredentialContext, *, retain_browser_authority: bool) -> CredentialContext:
    """Keep an issued certificate independent of its browser transport."""
    if retain_browser_authority and credential.kind in {"session", "temporary"}:
        if resolve_principal(credential.principal) != credential.principal:
            raise ValueError("VPN principal unavailable")
        return credential
    return resolve_current_credential(credential)


def admit_vpn_profile_authority(
    credential: CredentialContext,
    request_id: UUID,
    *,
    participation: bool = False,
    retain_browser_authority: bool = False,
) -> dict[str, object]:
    """Use the owning CMS/CTF decision, separately from the pool workload."""

    current = _resolve_profile_credential(credential, retain_browser_authority=retain_browser_authority)
    projection = project_range_authority(request_id)
    leaf = TargetRef("range", projection.public_uuid)
    if resolve_credential_scope(leaf) != projection.scope:
        raise ValueError("VPN range unavailable")
    action, target = "range.access", leaf
    if participation or current.kind == "temporary":
        if projection.parent.type != "event":
            raise ValueError("VPN participation unavailable")
        require_range_vpn_participation(current, request_id, projection.parent.uuid)
        action, target = "event.participate", projection.parent
    else:
        require_authorization(
            AuthorizationRequest(
                current.principal, action, leaf, projection.scope, current.ceiling, parent=projection.parent
            )
        )
    runtime = Range.objects.select_related("request").get(request__request_id=request_id)
    if (
        runtime.status != "ready"
        or runtime.resource_generation is None
        or project_range_authority(request_id) != projection
        or resolve_credential_scope(leaf) != projection.scope
    ):
        raise ValueError(_VPN_PROFILE_UNAVAILABLE)
    return {
        **credential_reference_fields(current),
        "authority_kind": "principal",
        "authority_action": action,
        "authority_target_type": target.type,
        "authority_target_uuid": target.uuid,
        "authority_parent_type": projection.parent.type,
        "authority_parent_uuid": projection.parent.uuid,
        "authority_scope_kind": projection.scope.kind,
        "authority_account_uuid": projection.scope.account_uuid,
        "authority_organization_uuid": projection.scope.organization_uuid,
        "authority_workspace_uuid": projection.scope.workspace_uuid,
        "authority_owner_uuid": projection.owner_principal_uuid,
        "authority_resource_uuid": projection.public_uuid,
        "authority_binding_digest": range_runtime_binding_digest(runtime),
    }


def assert_profile_runtime(row: VpnAccessProfile, *, pending: bool = False) -> tuple[VpnDestination, ...]:
    """Fence the certificate's exact range generation and current destination."""

    runtime = row.range
    capability = parse_openvpn_capability(runtime.remote_access_capability)
    if (
        row.state not in ({"pending"} if pending else {"ready"})
        or row.revoked_at is not None
        or row.expires_at <= timezone.now()
        or (runtime.status, runtime.resource_generation) != ("ready", row.resource_generation)
        or runtime.request is None
        or runtime.request.request_id != row.generation
        or row.authority_binding_digest != range_runtime_binding_digest(runtime)
        or capability.teardown_at <= timezone.now()
    ):
        raise ValueError(_VPN_PROFILE_UNAVAILABLE)
    return _member_destinations(runtime, capability.target_refs)


def authorize_vpn_profile(row: VpnAccessProfile) -> tuple[VpnDestination, ...]:
    """Revalidate the original authority and compare its admitted facts."""
    destination = assert_profile_runtime(row)
    fields = admit_vpn_profile_authority(
        credential_reference_from_record(row),
        row.generation,
        participation=row.authority_action == "event.participate",
        retain_browser_authority=True,
    )
    if any(getattr(row, name) != value for name, value in fields.items()):
        raise ValueError(_VPN_PROFILE_UNAVAILABLE)
    return destination
