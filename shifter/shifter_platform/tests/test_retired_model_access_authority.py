"""Authority retired with the model broker (#2909) narrows stored credentials, never fails them open."""

from __future__ import annotations

import importlib
from datetime import timedelta
from uuid import uuid4

import pytest
from django.apps import apps
from django.utils import timezone

from shared.operation_authority import credential_reference_from_record
from shared.retired_authorization import RETIRED_ACTIONS, RETIRED_SCOPES

pytestmark = pytest.mark.django_db

_RETIRED_ACTION = "workspace.publish_model_access"
_RETIRED_ACTION_SCOPE = "authorization:organization.manage_model_sources"
_RETIRED_SCOPE = "model-access:sharing:read"
_KEPT_ACTIONS = ("range.manage", "range.read")
_KEPT_SCOPE = "mission_control:range:read"


def _migration(label: str):
    return importlib.import_module(label)


def test_retired_values_name_every_removed_action_and_scope():
    from shared.api_tokens.scopes import KNOWN_SCOPES
    from shared.authorization.catalog import ACTION_CATALOG

    assert {
        "account.manage_model_sources",
        "installation.manage_model_sources",
        "organization.manage_model_sources",
        "workspace.manage_model_sources",
        "workspace.publish_model_access",
    } == RETIRED_ACTIONS
    assert {f"authorization:{action}" for action in RETIRED_ACTIONS} <= RETIRED_SCOPES
    assert not RETIRED_ACTIONS & {action.code for action in ACTION_CATALOG}
    assert not RETIRED_SCOPES & KNOWN_SCOPES


def _recorded(django_user_model, ceiling: tuple[str, ...], scopes: tuple[str, ...]):
    from management.services import principal_for_user
    from mission_control.models import GuacamoleBootstrapRequest

    user = django_user_model.objects.create_user(username=f"retired-{uuid4().hex[:8]}@example.test")
    return GuacamoleBootstrapRequest.objects.create(
        protocol="rdp",
        target_id="synthetic-target",
        expires_at=timezone.now() + timedelta(minutes=5),
        initiating_principal_uuid=principal_for_user(user).uuid,
        initiating_principal_kind="human",
        credential_kind="session",
        credential_uuid=uuid4(),
        credential_ceiling_actions="\n".join(sorted(ceiling)),
        credential_scopes="\n".join(sorted(scopes)),
    )


def test_recorded_authority_drops_only_retired_values(django_user_model):
    row = _recorded(django_user_model, (*_KEPT_ACTIONS, _RETIRED_ACTION), (_KEPT_SCOPE, _RETIRED_SCOPE))

    credential = credential_reference_from_record(row)

    assert credential.ceiling.actions == frozenset(_KEPT_ACTIONS)
    assert credential.scopes == frozenset({_KEPT_SCOPE})
    assert not credential.ceiling.permits(_RETIRED_ACTION)


@pytest.mark.parametrize(
    ("ceiling", "scopes"),
    [
        ((*_KEPT_ACTIONS, "workspace.unregistered_action"), ()),
        (_KEPT_ACTIONS, (_KEPT_SCOPE, "model-access:unregistered:read")),
    ],
)
def test_recorded_authority_still_fails_closed_on_other_unknown_values(django_user_model, ceiling, scopes):
    row = _recorded(django_user_model, ceiling, scopes)

    with pytest.raises(ValueError):
        credential_reference_from_record(row)


def test_tokens_and_admissions_with_retired_scopes_are_retired(django_user_model):
    from knox.models import AuthToken

    from management.models import Principal, ProviderBinding, ServiceCredentialAdmission
    from management.services import principal_for_user
    from shared.api_tokens.models import ApiToken

    user = django_user_model.objects.create_user(username="retired-token@example.test")
    kept_token, _raw = ApiToken.create_token(name="kept", created_by=user, scopes=[_KEPT_SCOPE])
    native, _raw = AuthToken.objects.create(user=user, expiry=timedelta(days=1))
    # Scopes are immutable after insert, so the historical row is inserted with its retired scope.
    retired_token = ApiToken.objects.create(
        name="retired",
        token_id=uuid4().hex,
        knox_token=native,
        scopes=[_KEPT_SCOPE, _RETIRED_SCOPE],
        principal_uuid=principal_for_user(user).uuid,
        created_by=user,
        expires_at=native.expiry,
    )
    service = Principal.objects.create(kind="service", name="Synthetic service")
    binding = ProviderBinding.objects.create(principal=service, issuer="https://accounts.google.com", subject="1" * 21)
    kept_admission = ServiceCredentialAdmission.objects.create(
        binding=binding, audience="https://portal.example.test", scopes=[_KEPT_SCOPE]
    )
    retired_admission = ServiceCredentialAdmission.objects.create(
        binding=binding, audience="https://portal.example.test/other", scopes=[_RETIRED_ACTION_SCOPE, _KEPT_SCOPE]
    )

    _migration("shared.migrations.0033_retire_model_access_scopes").scrub(apps, None)
    _migration("management.migrations.0023_retire_model_access_scopes").scrub(apps, None)

    for row in (kept_token, retired_token, kept_admission, retired_admission):
        row.refresh_from_db()
    assert kept_token.revoked_at is None
    assert retired_token.revoked_at is not None
    assert retired_token.scopes == [_KEPT_SCOPE, _RETIRED_SCOPE]
    assert kept_admission.is_active
    assert not retired_admission.is_active


def test_authorization_journal_rows_for_retired_actions_are_deleted():
    from workspaces.models import AuthorizationOperation

    def operation(action: str, generation: int) -> AuthorizationOperation:
        return AuthorizationOperation.objects.create(
            idempotency_namespace="synthetic",
            idempotency_key=action,
            request_digest="0" * 64,
            fence_key="synthetic-fence",
            generation=generation,
            state=AuthorizationOperation.State.CONFIRMED,
            actor_uuid=uuid4(),
            actor_kind="human",
            subject_kind="principal",
            subject_uuid=uuid4(),
            action=action,
            effect="allow",
            target_kind="workspace",
            target_uuid=uuid4(),
            scope_kind="account",
            model_id="0" * 26,
            credential_digest="0" * 64,
        )

    retired = operation(_RETIRED_ACTION, 1)
    kept = operation("workspace.manage_members", 2)

    _migration("workspaces.migrations.0026_retire_model_access_actions").scrub(apps, None)

    assert not AuthorizationOperation.objects.filter(pk=retired.pk).exists()
    assert AuthorizationOperation.objects.filter(pk=kept.pk).exists()


def test_ctf_initialization_intent_loses_model_sources_and_retired_authority():
    clean = _migration("ctf.migrations.0090_retire_model_access_records").clean_initialization_intent
    authority = {
        "principal_uuid": str(uuid4()),
        "principal_kind": "human",
        "credential_kind": "session",
        "credential_uuid": str(uuid4()),
        "ceiling_actions": sorted((*_KEPT_ACTIONS, _RETIRED_ACTION)),
        "scopes": sorted((_KEPT_SCOPE, _RETIRED_SCOPE)),
    }
    intent = {"authority": authority, "model_sources": None, "content_digest": None}

    cleaned = clean(intent)

    assert cleaned == {
        "authority": authority | {"ceiling_actions": list(_KEPT_ACTIONS), "scopes": [_KEPT_SCOPE]},
        "content_digest": None,
    }
    from ctf.services.event.initialization import _InitializationIntent

    _InitializationIntent.model_validate(cleaned)
