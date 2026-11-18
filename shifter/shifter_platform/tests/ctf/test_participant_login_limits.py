"""CTF participant sign-in limits: failed attempts per account and per source (#2973)."""

from __future__ import annotations

import logging

import pytest
from django.core.cache import caches
from django.urls import reverse

from ctf.services.participant.accounts import create_participant_accounts

from .conftest import TEST_CTF_BOOTSTRAP_PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_login_rate_limit_cache():
    caches["launch_rate_limit"].clear()


def test_ctf_login_rate_limits_repeated_failures(client, standard_user, settings):
    settings.CTF_LOGIN_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = 20
    settings.CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300

    client.post(reverse("ctf:ctf_login"), {"username": standard_user.username, "password": "wrong"})
    client.post(reverse("ctf:ctf_login"), {"username": standard_user.username, "password": "wrong"})
    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": standard_user.username, "password": "wrong"},
    )

    assert response.status_code == 429
    assert response["Retry-After"] == "300"


def test_ctf_login_allows_event_users_behind_shared_source(client, settings):
    settings.CTF_LOGIN_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = 6
    settings.CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300

    for participant_number in range(6):
        response = client.post(
            reverse("ctf:ctf_login"),
            {"username": f"event-participant-{participant_number}", "password": "wrong"},
        )
        assert response.status_code == 200

    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": "event-participant-7", "password": "wrong"},
    )

    assert response.status_code == 429
    assert response["Retry-After"] == "300"


def test_ctf_login_successes_do_not_consume_the_shared_source_budget(
    client, ctf_event_active, organizer_credential, monkeypatch, settings
):
    """Participants behind one venue address can all sign in; only failures charge (#2973)."""
    settings.CTF_LOGIN_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participants = create_participant_accounts(ctf_event_active.id, count=4, actor=organizer_credential)

    for participant in participants:
        client.logout()
        response = client.post(
            reverse("ctf:ctf_login"),
            {"username": participant.user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
        )
        assert response.status_code == 302

    client.logout()
    for _attempt in range(2):
        response = client.post(reverse("ctf:ctf_login"), {"username": "unknown-user", "password": "wrong"})
        assert response.status_code == 200
    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": participants[0].user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
    )
    assert response.status_code == 429


def test_ctf_login_limiter_outage_fails_closed_and_is_logged(client, standard_user, monkeypatch, caplog):
    from ctf.views import participant_auth

    def _cache_down(*_args, **_kwargs):
        raise ConnectionError("rate limit backend unavailable")

    # Fail the shared rate-limit cache backend, not a first-party helper (ADR-019-R1).
    monkeypatch.setattr(caches["launch_rate_limit"], "add", _cache_down)
    response = client.post(reverse("ctf:ctf_login"), {"username": standard_user.username, "password": "wrong"})

    assert response.status_code == 503
    assert response["Retry-After"] == "60"
    failures = [record for record in caplog.records if record.name == participant_auth.logger.name]
    assert [record.levelno for record in failures] == [logging.ERROR]
    assert failures[0].exc_info is not None
