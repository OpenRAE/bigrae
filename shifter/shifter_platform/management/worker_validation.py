"""Fixed, server-only native credentials for operator worker qualification."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.api_tokens.audit import TokenEvent, record_token_event
from shared.api_tokens.cli import credential_from_proof
from shared.api_tokens.models import ApiToken
from shared.api_tokens.policy import require_personal_token_grant
from shared.authorization import AuthorizationRequest, CredentialCeiling, TargetRef
from shared.authorization.policy import require_authorization, scope_parent
from shared.credentials import CredentialContext, resolve_credential_scope
from shared.identity_scope import PrincipalRef, ResourceScope

from .principals import human_principal_user_id, resolve_principal_uuid

_CONTEXT = "operator worker validation"
_RANGE_ACTIONS = frozenset({"range.read", "range.access", "range.manage"})


@contextmanager
def issue_worker_validation_credentials(
    principal_uuid: UUID, *, scope: ResourceScope, worker_ids: tuple[UUID, ...]
) -> Iterator[Callable[[TargetRef], CredentialContext]]:
    """Issue exact native proof to the recorded-operator task and revoke every issue.

    The trusted operator command validates the recorded bootstrap selection. Leaf proof remains
    unavailable until its worker exists in the selected native customer scope.
    """
    permissions = _validation_permissions(scope, worker_ids)
    principal = resolve_principal_uuid(principal_uuid)
    require_personal_token_grant(principal)
    _authorize_validation(principal, scope, permissions)
    issued, proofs = _issue_validation(principal, permissions)
    try:

        def credential(target: TargetRef) -> CredentialContext:
            """Authenticate exact proof only after native target-scope resolution."""
            if target not in proofs:
                raise ValueError("Worker validation target is unavailable")
            if target.type != "installation" and resolve_credential_scope(target) != scope:
                raise ValueError("Worker validation target scope changed")
            return credential_from_proof(proofs[target])

        yield credential
    finally:
        _revoke_validation(issued, principal_uuid)


def _validation_permissions(scope: ResourceScope, worker_ids: tuple[UUID, ...]) -> dict[TargetRef, frozenset[str]]:
    """Fix the action ceiling independently for configuration, launch and each worker."""
    if (
        scope.kind != "account"
        or not 1 <= len(worker_ids) <= 2
        or len(set(worker_ids)) != len(worker_ids)
        or any(not isinstance(identifier, UUID) or not identifier.int for identifier in worker_ids)
    ):
        raise ValueError("Worker validation selection is invalid")
    parent = scope_parent(scope)
    if resolve_credential_scope(parent) != scope:
        raise ValueError("Worker validation scope is unavailable")
    permissions = {
        TargetRef("installation"): frozenset({"installation.manage_cloud_authority"}),
        parent: frozenset({f"{parent.type}.launch_range"}),
        **{TargetRef("range", identifier): _RANGE_ACTIONS for identifier in worker_ids},
    }
    return permissions


def _authorize_validation(
    principal: PrincipalRef, scope: ResourceScope, permissions: dict[TargetRef, frozenset[str]]
) -> None:
    """Require current operator and parent permissions before issuance."""
    parent = scope_parent(scope)
    for target in (TargetRef("installation"), parent):
        for action in permissions[target]:
            require_authorization(
                AuthorizationRequest(
                    principal,
                    action,
                    target,
                    ResourceScope("installation") if target.type == "installation" else scope,
                    CredentialCeiling(permissions[target], target),
                )
            )


def _issue_validation(
    principal: PrincipalRef, permissions: dict[TargetRef, frozenset[str]]
) -> tuple[list[ApiToken], dict[TargetRef, str]]:
    """Commit all exact native issues and strict audit records atomically."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(pk=human_principal_user_id(principal))
    with transaction.atomic():
        pending = []
        proofs = {}
        for target, actions in permissions.items():
            token, proof = ApiToken.create_token(
                name="worker-validation",
                created_by=user,
                scopes=["authorization:" + action for action in sorted(actions)],
                expires_at=timezone.now() + timedelta(minutes=35),
                target=target,
            )
            record_token_event(
                TokenEvent.CREATED,
                token_id=token.token_id,
                token_pk=token.pk,
                actor_principal_uuid=principal.uuid,
                context=_CONTEXT,
            )
            pending.append(token)
            proofs[target] = proof
    return pending, proofs


def _revoke_validation(issued: list[ApiToken], principal_uuid: UUID) -> None:
    """Attempt every native revocation and fail the task if any cannot complete."""
    failed = False
    for token in issued:
        try:
            token.revoke()
            record_token_event(
                TokenEvent.REVOKED,
                token_id=token.token_id,
                token_pk=token.pk,
                actor_principal_uuid=principal_uuid,
                context=_CONTEXT,
            )
        except Exception:  # noqa: BLE001  # attempt every revocation and suppress credential-bearing failures
            failed = True
    if failed:
        raise ValueError("Worker validation credential revocation failed") from None
