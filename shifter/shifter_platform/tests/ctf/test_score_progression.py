"""Score progression for the leading scoreboard rows (#3004, ADR-028-R3).

Database-backed tests: each series must end at the row's published score and
follow the board's freeze, bracket, eligibility, and team deduplication rules.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import count

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ParticipantRole, ParticipantStatus
from ctf.models import CTFAward, CTFBracket, CTFChallenge, CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.scoring import (
    PROGRESSION_LIMIT,
    get_score_progression,
    get_scoreboard,
    get_team_scoreboard,
    recompute_participant_score,
    recompute_team_score,
)

from ._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db

_SEQ = count()


@pytest.fixture
def started_event(ctf_event):
    """The solo event, started two hours ago and open for six more."""
    now = timezone.now()
    ctf_event.event_start = now - timedelta(hours=2)
    ctf_event.event_end = now + timedelta(hours=6)
    ctf_event.save(update_fields=["event_start", "event_end"])
    return ctf_event


@pytest.fixture
def started_team_event(ctf_event_team):
    """The team event, started two hours ago and open for six more."""
    now = timezone.now()
    ctf_event_team.event_start = now - timedelta(hours=2)
    ctf_event_team.event_end = now + timedelta(hours=6)
    ctf_event_team.save(update_fields=["event_start", "event_end"])
    return ctf_event_team


def _player(event, name, *, team=None, bracket=None, **fields):
    return CTFParticipant.objects.create(
        event=event,
        email=f"p{next(_SEQ)}@example.test",
        name=name,
        team=team,
        bracket=bracket,
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
        **fields,
    )


def _challenge(event, points):
    return CTFChallenge.objects.create(
        event=event,
        name=f"Challenge {next(_SEQ)}",
        description="Synthetic challenge",
        category=ChallengeCategory.WEB.value,
        points=points,
    )


def _solve(participant, challenge, at, points=None):
    submission = CTFSubmission.objects.create(
        participant=participant,
        challenge=challenge,
        submitted_flag="FLAG{x}",
        is_correct=True,
        points_awarded=challenge.points if points is None else points,
        attempt_number=1,
    )
    CTFSubmission.objects.filter(pk=submission.pk).update(submitted_at=at)
    recompute_participant_score(participant.id)
    recompute_team_score(participant.team_id)


def _award(participant, points, at):
    award = CTFAward.objects.create(
        event=participant.event,
        participant=participant,
        points=points,
        reason="Bonus",
        granted_by=participant.event.created_by,
    )
    CTFAward.objects.filter(pk=award.pk).update(created_at=at)
    recompute_participant_score(participant.id)
    recompute_team_score(participant.team_id)


def _scores(series):
    return [point["score"] for point in series["points"]]


def test_individual_series_steps_through_solves_and_awards(started_event):
    start = started_event.event_start
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), start + timedelta(minutes=10))
    _solve(alice, _challenge(started_event, 200), start + timedelta(minutes=30))
    _award(alice, -50, start + timedelta(minutes=40))

    rows = get_scoreboard(started_event.id)
    result = get_score_progression(started_event, rows, team=False)

    (series,) = result["series"]
    assert series["id"] == str(alice.id)
    assert series["rank"] == 1
    assert _scores(series) == [0, 100, 300, 250]
    assert series["points"][0]["at"] == start.isoformat()
    assert _scores(series)[-1] == rows[0]["score"]
    assert result["starts_at"] == start.isoformat()


def test_series_carry_no_challenge_names_or_award_reasons(started_event):
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), started_event.event_start + timedelta(minutes=5))
    _award(alice, 10, started_event.event_start + timedelta(minutes=6))

    result = get_score_progression(started_event, get_scoreboard(started_event.id), team=False)

    assert set(result["series"][0]) == {"id", "name", "rank", "points"}
    assert {key for point in result["series"][0]["points"] for key in point} == {"at", "score"}


def test_pre_start_points_fold_into_the_origin(started_event):
    alice = _player(started_event, "Alice")
    _award(alice, 25, started_event.event_start - timedelta(hours=1))
    _solve(alice, _challenge(started_event, 100), started_event.event_start + timedelta(minutes=5))

    result = get_score_progression(started_event, get_scoreboard(started_event.id), team=False)

    assert _scores(result["series"][0]) == [25, 125]


def test_freeze_cutoff_excludes_later_points_and_ends_the_axis(started_event):
    start = started_event.event_start
    freeze_at = start + timedelta(hours=1)
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), start + timedelta(minutes=10))
    _solve(alice, _challenge(started_event, 200), freeze_at + timedelta(minutes=1))
    _award(alice, 50, freeze_at)

    rows = get_scoreboard(started_event.id, freeze_at=freeze_at)
    result = get_score_progression(started_event, rows, team=False, freeze_at=freeze_at)

    assert _scores(result["series"][0]) == [0, 100]
    assert rows[0]["score"] == 100
    assert result["ends_at"] == freeze_at.isoformat()


def test_series_cover_only_the_leading_rows_in_rank_order(started_event):
    challenge = _challenge(started_event, 10)
    players = [_player(started_event, f"Player {index}") for index in range(PROGRESSION_LIMIT + 2)]
    for index, player in enumerate(players):
        _solve(player, challenge, started_event.event_start + timedelta(minutes=1), points=10 * (index + 1))

    rows = get_scoreboard(started_event.id)
    result = get_score_progression(started_event, rows, team=False)

    assert len(result["series"]) == PROGRESSION_LIMIT
    assert [series["id"] for series in result["series"]] == [row["participant_id"] for row in rows[:PROGRESSION_LIMIT]]


def test_team_series_count_a_shared_challenge_once_at_its_best_points(started_team_event):
    start = started_team_event.event_start
    team = CTFTeam.objects.create(event=started_team_event, name="Red")
    first = _player(started_team_event, "First", team=team)
    second = _player(started_team_event, "Second", team=team)
    observer = _player(started_team_event, "Watcher", team=team, role=ParticipantRole.OBSERVER.value)
    shared = _challenge(started_team_event, 100)
    _solve(first, shared, start + timedelta(minutes=10), points=80)
    _solve(second, shared, start + timedelta(minutes=20), points=100)
    _solve(second, _challenge(started_team_event, 50), start + timedelta(minutes=30))
    _solve(observer, _challenge(started_team_event, 300), start + timedelta(minutes=35))
    _award(first, 5, start + timedelta(minutes=40))

    rows = get_team_scoreboard(started_team_event.id)
    result = get_score_progression(started_team_event, rows, team=True)

    (series,) = result["series"]
    assert series["id"] == str(team.id)
    assert _scores(series) == [0, 80, 100, 150, 155]
    assert _scores(series)[-1] == rows[0]["score"]


def test_team_bracket_series_count_only_bracket_members(started_team_event):
    start = started_team_event.event_start
    bracket = CTFBracket.objects.create(event=started_team_event, name="Students")
    team = CTFTeam.objects.create(event=started_team_event, name="Blue")
    inside = _player(started_team_event, "Inside", team=team, bracket=bracket)
    outside = _player(started_team_event, "Outside", team=team)
    _solve(inside, _challenge(started_team_event, 100), start + timedelta(minutes=10))
    _solve(outside, _challenge(started_team_event, 200), start + timedelta(minutes=20))

    rows = get_team_scoreboard(started_team_event.id, bracket_id=bracket.id)
    result = get_score_progression(started_team_event, rows, team=True, bracket_id=bracket.id)

    assert _scores(result["series"][0]) == [0, 100]
    assert rows[0]["score"] == 100


def test_deleted_member_points_leave_team_history_and_boards(started_team_event):
    from ctf.services.participant import delete_participant

    start = started_team_event.event_start
    freeze_at = start + timedelta(hours=1)
    team = CTFTeam.objects.create(event=started_team_event, name="Green")
    kept = _player(started_team_event, "Kept", team=team)
    removed = _player(started_team_event, "Removed", team=team)
    _solve(kept, _challenge(started_team_event, 100), start + timedelta(minutes=10))
    _solve(removed, _challenge(started_team_event, 200), start + timedelta(minutes=20))
    _award(removed, 30, start + timedelta(minutes=25))

    delete_participant(removed.id)

    live = get_team_scoreboard(started_team_event.id)
    frozen = get_team_scoreboard(started_team_event.id, freeze_at=freeze_at)
    assert live[0]["score"] == 100
    assert frozen[0]["score"] == 100
    assert frozen[0]["member_count"] == 1
    result = get_score_progression(started_team_event, frozen, team=True, freeze_at=freeze_at)
    assert _scores(result["series"][0]) == [0, 100]


def test_public_scoreboard_publishes_progression_for_the_selected_board(client, started_event):
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), started_event.event_start + timedelta(minutes=5))

    response = call_json(client, "get", "api_scoreboard", kwargs={"event_id": started_event.id})

    assert response.status_code == 200
    (series,) = response.json()["progression"]["series"]
    assert series["name"] == "Alice"
    assert _scores(series) == [0, 100]


def test_hidden_public_scoreboard_publishes_no_progression(client, started_event):
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), started_event.event_start + timedelta(minutes=5))
    started_event.scoreboard_visibility = "hidden"
    started_event.save(update_fields=["scoreboard_visibility"])

    response = call_json(client, "get", "api_scoreboard", kwargs={"event_id": started_event.id})

    assert response.status_code == 200
    assert response.json()["progression"] is None


def test_organizer_scoreboard_publishes_live_progression(authenticated_organizer_client, started_event):
    start = started_event.event_start
    started_event.scoreboard_freeze_at = start + timedelta(hours=1)
    started_event.save(update_fields=["scoreboard_freeze_at"])
    alice = _player(started_event, "Alice")
    _solve(alice, _challenge(started_event, 100), start + timedelta(minutes=90))

    response = call_json(
        authenticated_organizer_client, "get", "api_organizer_scoreboard", kwargs={"event_id": started_event.id}
    )

    assert response.status_code == 200
    assert _scores(response.json()["progression"]["series"][0]) == [0, 100]
