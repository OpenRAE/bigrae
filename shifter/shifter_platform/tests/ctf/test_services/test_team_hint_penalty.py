"""Team-mode hint penalties apply to the whole team (#2978).

Integration-style tests using real DB objects.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.models import CTFChallenge, CTFEvent, CTFHint, CTFParticipant, CTFTeam
from ctf.services.hint import get_total_hint_penalty, get_unlocked_hints, hint_penalties_for_solvers, use_hint

pytestmark = pytest.mark.django_db

User = get_user_model()


def _event(organizer_user, *, team_mode: bool) -> CTFEvent:
    return CTFEvent.objects.create(
        name="Team Hint Event" if team_mode else "Solo Hint Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        team_mode=team_mode,
        team_size_limit=20 if team_mode else None,
    )


def _participant(event: CTFEvent, name: str, team: CTFTeam | None = None) -> CTFParticipant:
    user = User.objects.create_user(username=f"{name}-{event.pk.hex[:6]}", password="x")
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=f"{name}@example.com",
        name=name,
        team=team,
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


def _challenge_with_hints(event: CTFEvent) -> tuple[CTFChallenge, CTFHint, CTFHint]:
    challenge = CTFChallenge.objects.create(
        event=event,
        name="Hinted",
        description="Test",
        category=ChallengeCategory.WEB.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
    )
    first = CTFHint.objects.create(challenge=challenge, text="First hint", penalty=30, order=0)
    second = CTFHint.objects.create(challenge=challenge, text="Second hint", penalty=20, order=1)
    return challenge, first, second


@pytest.fixture
def team_setup(organizer_user):
    event = _event(organizer_user, team_mode=True)
    team = CTFTeam.objects.create(event=event, name="Alpha")
    unlocker = _participant(event, "unlocker", team)
    solver = _participant(event, "solver", team)
    rival = _participant(event, "rival", CTFTeam.objects.create(event=event, name="Bravo"))
    challenge, first, second = _challenge_with_hints(event)
    return event, team, unlocker, solver, rival, challenge, first, second


def test_a_teammates_unlock_counts_for_the_whole_team(team_setup):
    _event_row, _team, unlocker, solver, rival, challenge, first, _second = team_setup

    use_hint(unlocker.id, first.id)

    assert get_total_hint_penalty(solver.id, challenge.id) == 30
    assert [hint.id for hint in get_unlocked_hints(solver.id, challenge.id)] == [first.id]
    assert get_total_hint_penalty(rival.id, challenge.id) == 0
    assert hint_penalties_for_solvers(challenge.id, [solver.id, rival.id]) == {solver.id: 30, rival.id: 0}


def test_a_hint_the_team_already_unlocked_is_not_charged_twice(team_setup):
    _event_row, _team, unlocker, solver, _rival, challenge, first, second = team_setup

    use_hint(unlocker.id, first.id)
    repeat = use_hint(solver.id, first.id)
    use_hint(solver.id, second.id)  # The team already unlocked the first hint, so the order check passes.

    assert repeat["already_unlocked"] is True
    assert get_total_hint_penalty(unlocker.id, challenge.id) == 50
    assert get_total_hint_penalty(solver.id, challenge.id) == 50


def test_leaving_the_team_does_not_remove_the_teams_penalty(team_setup):
    _event_row, _team, unlocker, solver, _rival, challenge, first, _second = team_setup

    use_hint(unlocker.id, first.id)
    unlocker.team = None
    unlocker.save(update_fields=["team"])

    assert get_total_hint_penalty(solver.id, challenge.id) == 30
    assert get_total_hint_penalty(unlocker.id, challenge.id) == 30


def test_solo_events_keep_per_participant_penalties(organizer_user):
    event = _event(organizer_user, team_mode=False)
    first_player = _participant(event, "first")
    second_player = _participant(event, "second")
    challenge, first, _second = _challenge_with_hints(event)

    use_hint(first_player.id, first.id)

    assert get_total_hint_penalty(first_player.id, challenge.id) == 30
    assert get_total_hint_penalty(second_player.id, challenge.id) == 0
