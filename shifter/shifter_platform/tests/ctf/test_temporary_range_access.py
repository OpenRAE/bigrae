"""Normal participant sessions retain event scope when opening their own guest."""

import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from cms.models import RangeInstance
from ctf.models import CTFEvent, CTFParticipant
from engine.models import Range
from tests.cms.conftest import make_pack as make_pack
from tests.ctf.test_range_launch_crash_recovery import launch_event as launch_event
from tests.integration.authorization.test_openfga_released_server import provider as provider

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def login_participant(participant):
    from config.session_credentials import session_credential
    from management.services import set_ctf_password_change_required

    user = participant.user
    user.set_password("Synthetic-participant-password-2785")
    user.save(update_fields=["password"])
    set_ctf_password_change_required(user, False)
    client = Client()
    response = client.post(
        "/ctf/login/", {"username": user.username, "password": "Synthetic-participant-password-2785"}
    )
    assert response.status_code == 302
    assert response.url == "/ctf/range/"
    return client, session_credential(user, client.session)


@pytest.fixture
def participant_remote(launch_event, organizer_credential, monkeypatch):
    from ctf.services.participant.accounts import create_participant_accounts
    from ctf.services.range import provision_participant_range

    launch_event.status = "active"
    launch_event.event_start = timezone.now() - timedelta(minutes=5)
    launch_event.event_end = timezone.now() + timedelta(hours=2)
    launch_event.save(update_fields=["status", "event_start", "event_end"])
    participant = create_participant_accounts(launch_event.pk, count=1, actor=organizer_credential)[0]
    provision_participant_range(participant.pk, actor=organizer_credential)
    participant.refresh_from_db()
    leaf = RangeInstance.objects.get(pk=participant.range_instance_id)
    native = Range.objects.get(request__request_id=participant.range_request_id)
    guest = str(uuid4())
    native.status = "ready"
    native.resource_generation = uuid4()
    native.provisioned_instances = [
        {
            "uuid": guest,
            "os_type": "linux",
            "private_ip": "192.0.2.10",
            "ssh_username": "analyst",
            "ssh_key_secret_id": "synthetic-participant-key",
            "participant_access_channels": ["ssh"],
        }
    ]
    native.save(update_fields=["status", "resource_generation", "provisioned_instances"])
    leaf.status = "ready"
    leaf.save(update_fields=["status"])
    participant.range_status = "ready"
    participant.save(update_fields=["range_status"])
    client, credential = login_participant(participant)
    reads = []
    monkeypatch.setattr("engine.secrets.get_ssh_key", lambda key: reads.append(key) or "SYNTHETIC_PRIVATE_KEY")
    return SimpleNamespace(
        participant=participant,
        event=launch_event,
        organizer=organizer_credential,
        leaf=leaf,
        native=native,
        guest=guest,
        client=client,
        credential=credential,
        reads=reads,
    )


def test_normal_participant_opens_only_its_assigned_range(participant_remote):
    from cms.services import admit_range_remote_authority, connect_range_terminal

    case = participant_remote
    assert case.credential.kind == "temporary"
    assert case.credential.ceiling.actions == frozenset({"event.read", "event.participate"})
    transport = object()
    result = connect_range_terminal(case.credential, case.guest, connection_factory=lambda **_facts: transport)
    assert result is transport
    authority = admit_range_remote_authority(case.credential, case.guest)
    assert authority["authority_target_uuid"] == case.leaf.uuid
    assert authority["authority_owner_uuid"] == case.credential.principal.uuid
    assert case.reads == ["synthetic-participant-key"]


@pytest.mark.openfga
@pytest.mark.parametrize("denial", ["deny_event_participate", "excluded"])
def test_temporary_participation_with_released_policy_server(participant_remote, provider, monkeypatch, denial):
    from dataclasses import replace

    from openfga_sdk.client.models import ClientTuple, ClientWriteRequest

    from cms.services import connect_range_terminal
    from engine.services import project_range_authority
    from shared.authorization import port
    from shared.range_access_authority import range_action_request

    case = participant_remote
    projection = project_range_authority(case.participant.range_request_id)
    scope = projection.scope
    # These are synthetic policy ancestry facts, not participation grants.
    parents = [(f"account:{scope.account_uuid}", "installation", "installation:root")]
    parent_type, parent_uuid = "account", scope.account_uuid
    for kind, identity in (("organization", scope.organization_uuid), ("workspace", scope.workspace_uuid)):
        if identity is not None:
            parents.append((f"{kind}:{identity}", parent_type, f"{parent_type}:{parent_uuid}"))
            parent_type, parent_uuid = kind, identity
    event = f"event:{case.event.pk}"
    parents.append((event, parent_type, f"{parent_type}:{parent_uuid}"))
    provider._client.write(
        ClientWriteRequest(writes=[ClientTuple(user, relation, obj) for obj, relation, user in parents]),
        {"authorization_model_id": provider._settings.model_id},
    )
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    request = range_action_request(
        case.credential,
        "range.access",
        range_uuid=projection.public_uuid,
        request_uuid=projection.request_uuid,
        owner_uuid=projection.owner_principal_uuid,
        scope=scope,
        parent=projection.parent,
    )
    assert not provider.check(replace(request, temporary_participation=False)).allowed
    assert provider.check(request).allowed
    assert provider.batch_check((request,))[0].allowed
    transport = object()
    assert (
        connect_range_terminal(case.credential, case.guest, connection_factory=lambda **_facts: transport) is transport
    )
    case.reads.clear()
    provider._client.write(
        ClientWriteRequest(writes=[ClientTuple(f"principal:{case.credential.principal.uuid}", denial, event)]),
        {"authorization_model_id": provider._settings.model_id},
    )
    assert not provider.check(request).allowed
    assert not provider.batch_check((request,))[0].allowed
    with pytest.raises((PermissionError, ValueError)):
        connect_range_terminal(case.credential, case.guest, connection_factory=lambda **_facts: object())
    assert not case.reads


def test_normal_participant_can_queue_browser_ssh(participant_remote, settings, monkeypatch):
    from mission_control.guacamole_authority import renew_gateway_authority
    from mission_control.guacamole_bootstrap import consume_ready_url
    from mission_control.models import GuacamoleBootstrapRequest
    from tests.mission_control.test_principal_guacamole import Gateway

    case = participant_remote
    settings.GUACAMOLE_JSON_AUTH_SECRET = "0" * 32
    gateway = Gateway()
    monkeypatch.setattr("mission_control.guacamole.get_guacamole_client", lambda _config: gateway)
    response = case.client.post(
        "/api/v1/mission-control/guacamole/ssh-url/", {"instance_uuid": case.guest}, content_type="application/json"
    )
    assert response.status_code == 202, response.content
    identifier = response.json()["request_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        bootstrap = GuacamoleBootstrapRequest.objects.get(pk=identifier)
        if bootstrap.status in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert bootstrap.status == "succeeded"
    assert consume_ready_url(request_id=bootstrap.pk, credential=case.credential)
    assert renew_gateway_authority(str(bootstrap.pk))
    CTFParticipant.objects.filter(pk=case.participant.pk).update(status="banned")
    assert not renew_gateway_authority(str(bootstrap.pk))


def test_another_participant_cannot_open_the_same_event_guest(participant_remote):
    from cms.services import connect_range_terminal
    from ctf.services.participant.accounts import create_participant_accounts

    case = participant_remote
    other = create_participant_accounts(case.event.pk, count=1, actor=case.organizer)[0]
    _client, credential = login_participant(other)
    with pytest.raises((PermissionError, ValueError)):
        connect_range_terminal(credential, case.guest, connection_factory=lambda **_facts: object())
    assert not case.reads


@pytest.mark.parametrize("change", ["banned", "ended", "assignment", "channel", "policy"])
def test_participant_access_fails_before_secrets_on_changed_standing(participant_remote, monkeypatch, change):
    from cms.services import connect_range_terminal
    from shared.authorization import AuthorizationDecision, DecisionKind, port

    case = participant_remote
    if change == "banned":
        CTFParticipant.objects.filter(pk=case.participant.pk).update(status="banned")
    elif change == "ended":
        CTFEvent.objects.filter(pk=case.event.pk).update(status="ended")
    elif change == "assignment":
        CTFParticipant.objects.filter(pk=case.participant.pk).update(range_instance_id=None)
    elif change == "channel":
        case.native.provisioned_instances[0]["participant_access_channels"] = ["rdp"]
        case.native.save(update_fields=["provisioned_instances"])
    else:
        monkeypatch.setattr(
            port,
            "_provider_factory",
            lambda: SimpleNamespace(
                check=lambda _request: AuthorizationDecision(DecisionKind.EVALUATOR_ERROR, "evaluator_unavailable")
            ),
        )
    with pytest.raises((PermissionError, ValueError)):
        connect_range_terminal(case.credential, case.guest, connection_factory=lambda **_facts: object())
    assert not case.reads
