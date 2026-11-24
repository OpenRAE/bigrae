"""Team-mode flag submission policy through the real service and API."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.exceptions import CTFStateError
from ctf.models import CTFChallenge, CTFFlag, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.submission import submit_flag
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db
FLAG = "FLAG{team-submission}"


@pytest.fixture
def arena(ctf_event_active, participant_user):
    event = ctf_event_active
    event.team_mode = True
    event.team_size_limit = 4
    event.save(update_fields=["team_mode", "team_size_limit"])
    participant = CTFParticipant.objects.create(
        event=event,
        user=participant_user,
        email=participant_user.email,
        name="Team player",
        status="active",
        registered_at=timezone.now(),
    )
    challenge = CTFChallenge.objects.create(
        event=event, name="Team challenge", description="Test challenge", category="web", points=100
    )
    CTFFlag.objects.create(challenge=challenge, value=FLAG)
    return event, participant, challenge


def assert_no_submission_effects(participant):
    participant.refresh_from_db()
    assert not CTFSubmission.objects.filter(participant=participant).exists()
    assert participant.cached_score == 0
    assert participant.last_active_at is None


@pytest.mark.parametrize("flag,correct", [(FLAG, True), ("FLAG{wrong}", False)])
def test_teamless_submission_allowed_in_team_mode(arena, flag, correct):
    """#3000: a participant with no team competes as an individual in team mode."""
    _event, participant, challenge = arena
    assert participant.team_id is None
    submission = submit_flag(participant.pk, challenge.pk, flag)
    assert submission.is_correct is correct
    assert submission.points_awarded == (100 if correct else 0)
    participant.refresh_from_db()
    assert participant.cached_score == (100 if correct else 0)


@pytest.mark.parametrize("team_mode,has_team", [(False, False), (True, True)])
@pytest.mark.parametrize("flag,correct", [(FLAG, True), ("FLAG{wrong}", False)])
def test_eligible_submission_allowed(arena, team_mode, has_team, flag, correct):
    event, participant, challenge = arena
    event.team_mode = team_mode
    event.team_size_limit = 4 if team_mode else None
    event.save(update_fields=["team_mode", "team_size_limit"])
    if has_team:
        participant.team = CTFTeam.objects.create(event=event, name="Players")
        participant.save(update_fields=["team"])
    submission = submit_flag(participant.pk, challenge.pk, flag)
    assert submission.is_correct is correct
    assert submission.points_awarded == (100 if correct else 0)
    assert submission.attempt_number == 1


@pytest.mark.parametrize("invalid_team", ["deleted", "foreign"])
def test_invalid_membership_rejected(arena, ctf_event_team, invalid_team):
    """A present but stale or cross-event team reference still blocks submission.

    #3000 drops the "must have a team" rule, not the integrity check: a team a
    participant still names must be a live team of the same event, so a stale or
    cross-event reference cannot drive this event's team-score maintenance.
    """
    event, participant, challenge = arena
    team = CTFTeam.objects.create(event=event if invalid_team == "deleted" else ctf_event_team, name="Other team")
    CTFParticipant.objects.filter(pk=participant.pk).update(team=team)
    if invalid_team == "deleted":
        team.delete()
    with pytest.raises(CTFStateError, match="team"):
        submit_flag(participant.pk, challenge.pk, FLAG)
    assert_no_submission_effects(participant)


def test_foreign_team_rejected_before_external_verifier(arena, ctf_event_team, monkeypatch):
    from ctf.extensions import _flag_validators

    _event, participant, challenge = arena
    foreign_team = CTFTeam.objects.create(event=ctf_event_team, name="Other team")
    CTFParticipant.objects.filter(pk=participant.pk).update(team=foreign_team)
    calls = []

    def external_verifier(flag_obj, submitted):
        calls.append(submitted)
        return True

    monkeypatch.setitem(_flag_validators, "static", external_verifier)
    with pytest.raises(CTFStateError, match="team"):
        submit_flag(participant.pk, challenge.pk, FLAG)
    assert calls == []
    assert_no_submission_effects(participant)


def test_membership_removed_during_verification_scores_individually(arena, monkeypatch):
    from ctf.extensions import _flag_validators

    event, participant, challenge = arena
    team = CTFTeam.objects.create(event=event, name="Players")
    participant.team = team
    participant.save(update_fields=["team"])
    calls = []

    def external_verifier(flag_obj, submitted):
        CTFParticipant.objects.filter(pk=participant.pk).update(team=None)
        calls.append(submitted)
        return True

    monkeypatch.setitem(_flag_validators, "static", external_verifier)
    submission = submit_flag(participant.pk, challenge.pk, FLAG)
    assert calls == [FLAG]
    assert submission.is_correct is True
    assert submission.points_awarded == 100
    participant.refresh_from_db()
    assert participant.team_id is None
    assert participant.cached_score == 100
    team.refresh_from_db()
    assert team.cached_score == 0


def test_teamless_api_submission_allowed(arena, authenticated_participant_client):
    _event, participant, challenge = arena
    response = call_json(
        authenticated_participant_client,
        "post",
        "api_submit_flag",
        kwargs={"challenge_id": challenge.pk},
        body={"flag": FLAG},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["correct"] is True
    assert payload["points_awarded"] == 100
    participant.refresh_from_db()
    assert participant.cached_score == 100
