"""Installation principal-administration policy seam for management services."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser

from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext, resolve_current_credential, resolve_local_credential
from shared.identity_scope import ResourceScope

_DENIED = "Principal administration denied"


def require_principal_administration(
    actor: CredentialContext, provider: AuthorizationProvider | None
) -> CredentialContext:
    """Check the live installation action before any identity read or command."""
    try:
        if actor.kind == "temporary" or provider is None:
            raise PermissionError(_DENIED)
        actor = resolve_current_credential(actor)
        request = AuthorizationRequest(
            actor.principal,
            "installation.manage_principals",
            TargetRef("installation"),
            ResourceScope("installation"),
            actor.ceiling,
        )
        if not provider.check(request).allowed:
            raise PermissionError(_DENIED)
        return actor
    except Exception as exc:
        raise PermissionError(_DENIED) from exc


def fence_principal_administration(actor: CredentialContext) -> None:
    """Check local proof lifecycle again inside the owning write transaction."""
    try:
        if resolve_local_credential(actor) != actor:
            raise ValueError("Credential changed")
    except Exception as exc:
        raise PermissionError(_DENIED) from exc


def is_platform_operator(user: object | None) -> bool:
    """Return the single active, non-temporary deployment-operator predicate.

    Django staff/model permissions, groups, provider claims, tenancy roles, and
    CTF delegation do not satisfy this global authority.
    """
    from shared.auth import is_temporary_ctf_account

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False) or not getattr(user, "is_superuser", False):
        return False
    return not is_temporary_ctf_account(cast(AbstractBaseUser | AnonymousUser, user))
