"""Canonical range decisions for ordinary and event-bound participant proofs."""

from uuid import UUID

from shared.authorization import AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.range_workspace_aggregate import require_range_remote_participation


def range_action_request(
    credential: CredentialContext,
    action: str,
    *,
    range_uuid: UUID,
    request_uuid: UUID,
    owner_uuid: UUID,
    scope: ResourceScope,
    parent: TargetRef,
) -> AuthorizationRequest:
    """Use only owning-service facts; never broaden an event-bound credential."""
    if action == "range.access":
        if credential.kind == "temporary" and (
            parent.type != "event"
            or parent.uuid is None
            or credential.event_uuid != parent.uuid
            or credential.principal.uuid != owner_uuid
        ):
            raise ValueError("Participant range access unavailable")
        if parent.type == "event":
            if parent.uuid is None:
                raise ValueError("Participant range access unavailable")
            require_range_remote_participation(credential, request_uuid, parent.uuid, owner_uuid)
        if credential.kind == "temporary":
            return AuthorizationRequest(credential.principal, "event.participate", parent, scope, credential.ceiling)
    return AuthorizationRequest(
        credential.principal, action, TargetRef("range", range_uuid), scope, credential.ceiling, parent=parent
    )
