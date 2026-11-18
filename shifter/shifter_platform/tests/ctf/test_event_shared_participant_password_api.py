"""Event-shared initial participant password through the organizer API (#2975)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from tests.ctf._api_flow_helpers import call_json as _json

if TYPE_CHECKING:
    from django.test import Client

    from ctf.models import CTFEvent

pytestmark = pytest.mark.django_db

SHARED = "Venue-Entry-Phrase-2026"


@pytest.fixture(autouse=True)
def _no_provisioning(monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)


def _put(client: Client, event: CTFEvent, body: dict):
    return _json(client, "put", "api_event_detail", kwargs={"event_id": event.id}, body=body)


def _detail(client: Client, event: CTFEvent) -> dict:
    return _json(client, "get", "api_event_detail", kwargs={"event_id": event.id}).json()


def test_organizer_sets_reads_state_and_clears_the_shared_password(
    authenticated_organizer_client: Client, ctf_event: CTFEvent
):
    assert _put(authenticated_organizer_client, ctf_event, {"participant_password_override": SHARED}).status_code == 200
    ctf_event.refresh_from_db()
    assert ctf_event.participant_password_override == SHARED
    detail = _detail(authenticated_organizer_client, ctf_event)
    assert detail["participant_shared_password_set"] is True
    assert SHARED not in str(detail)
    assert "participant_password_override" not in detail

    assert _put(authenticated_organizer_client, ctf_event, {"participant_password_override": ""}).status_code == 200
    ctf_event.refresh_from_db()
    assert ctf_event.participant_password_override == ""
    assert _detail(authenticated_organizer_client, ctf_event)["participant_shared_password_set"] is False


def test_a_shared_password_that_fails_the_policy_is_refused(
    authenticated_organizer_client: Client, ctf_event: CTFEvent
):
    ctf_event.participant_password_override = ""
    ctf_event.save(update_fields=["participant_password_override"])

    response = _put(authenticated_organizer_client, ctf_event, {"participant_password_override": "123"})

    assert response.status_code == 400
    ctf_event.refresh_from_db()
    assert ctf_event.participant_password_override == ""


def test_imported_participants_sign_in_with_the_shared_password_and_are_listed_by_username(
    authenticated_organizer_client: Client, ctf_event_active: CTFEvent
):
    assert (
        _put(authenticated_organizer_client, ctf_event_active, {"participant_password_override": SHARED}).status_code
        == 200
    )
    rows = [{"name": f"Venue {n}", "email": f"venue{n}@example.com", "username": f"venue-{n}"} for n in range(3)]
    response = _json(
        authenticated_organizer_client,
        "post",
        "api_participant_import",
        kwargs={"event_id": ctf_event_active.id},
        body={"participants": rows},
    )
    assert response.status_code in (200, 201), response.content

    listed = _json(
        authenticated_organizer_client, "get", "api_participant_list", kwargs={"event_id": ctf_event_active.id}
    ).json()["participants"]
    assert {"venue-0", "venue-1", "venue-2"} <= {row["username"] for row in listed}

    from django.test import Client as ParticipantClient

    participant = ParticipantClient()
    signed_in = participant.post(reverse("ctf:ctf_login"), {"username": "venue-1", "password": SHARED})
    assert signed_in.status_code == 302
    assert signed_in.url == reverse("ctf:ctf_change_password")
