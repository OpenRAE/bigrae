"""Score progression for the leading scoreboard rows (#3004).

Builds a bounded score-over-time series for the first ``PROGRESSION_LIMIT``
rows of an already-ranked board. The series read the same authoritative
``CTFSubmission`` / ``CTFAward`` rows as the recompute scoreboard path, with the
same freeze cutoff, bracket filter, ranking eligibility, and team challenge
deduplication. Thus the last point of each series equals the row's score.
A series carries only timestamps and cumulative scores, never challenge names
or award reasons.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Q
from django.utils import timezone

from ctf.models import CTFAward, CTFSubmission
from ctf.services.participant import ranked_participant_q

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet

    from ctf.models import CTFEvent

# Series cap: the categorical chart palette has eight validated hues.
PROGRESSION_LIMIT = 8

# (competitor id, time, team challenge id or None, points). A None key adds the
# points directly; a challenge key counts the challenge once at its best points.
_ScoreEvent = tuple[str, datetime, "UUID | None", int]


def get_score_progression(
    event: CTFEvent,
    rows: list[dict[str, Any]],
    *,
    team: bool,
    freeze_at: datetime | None = None,
    bracket_id: UUID | None = None,
) -> dict[str, Any]:
    """Return the score-over-time series for the leading ``rows`` of one board.

    Args:
        event: The event that owns the board.
        rows: The ranked board rows, in published order.
        team: True for team rows (``team_id``), False for participant rows.
        freeze_at: The public freeze cutoff, or None for the live board.
        bracket_id: The bracket filter that selected ``rows``, if any.

    Returns:
        ``starts_at``, ``ends_at``, and one series per leading row with its
        ``points`` (``at``, cumulative ``score``) in time order.
    """
    leaders = rows[:PROGRESSION_LIMIT]
    id_key = "team_id" if team else "participant_id"
    ids = [str(row[id_key]) for row in leaders]
    score_events = _team_events(ids, freeze_at, bracket_id) if team else _participant_events(ids, freeze_at)
    starts_at = event.event_start
    series = {competitor: _Series(starts_at) for competitor in ids}
    for competitor, at, challenge_id, points in score_events:
        series[competitor].add(at, challenge_id, points)

    last_points = [point["at"] for entry in series.values() for point in entry.points[1:]]
    ends_at = freeze_at or min(timezone.now(), event.event_end)
    ends_at = max([ends_at, starts_at, *last_points])
    return {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "series": [
            {
                "id": competitor,
                "name": row["name"],
                "rank": row["rank"],
                "points": [{"at": p["at"].isoformat(), "score": p["score"]} for p in series[competitor].points],
            }
            for competitor, row in zip(ids, leaders, strict=True)
        ],
    }


class _Series:
    """One competitor's cumulative score; team challenges count once at their best points."""

    def __init__(self, starts_at: datetime) -> None:
        self.starts_at = starts_at
        self.score = 0
        self.best: dict[UUID, int] = {}
        self.points: list[dict[str, Any]] = [{"at": starts_at, "score": 0}]

    def add(self, at: datetime, challenge_id: UUID | None, points: int) -> None:
        """Apply one solve or award; record a point only when the score changes."""
        if challenge_id is None:
            delta = points
        else:
            previous = self.best.get(challenge_id)
            delta = points if previous is None else max(points - previous, 0)
            self.best[challenge_id] = points if previous is None else max(previous, points)
        if delta == 0:
            return
        self.score += delta
        if at <= self.starts_at:
            self.points[0]["score"] = self.score
        else:
            self.points.append({"at": at, "score": self.score})


def _participant_events(ids: list[str], freeze_at: datetime | None) -> list[_ScoreEvent]:
    """Solves and awards of individual competitors, as the participant score counts them."""
    if not ids:
        return []
    solves = _before(
        CTFSubmission.objects.filter(participant_id__in=ids, is_correct=True), "submitted_at", freeze_at
    ).values_list("participant_id", "submitted_at", "points_awarded")
    awards = _before(CTFAward.objects.filter(participant_id__in=ids), "created_at", freeze_at).values_list(
        "participant_id", "created_at", "points"
    )
    events: list[_ScoreEvent] = [(str(pid), at, None, pts) for pid, at, pts in solves]
    events.extend((str(pid), at, None, pts) for pid, at, pts in awards)
    events.sort(key=lambda item: item[1])
    return events


def _team_events(ids: list[str], freeze_at: datetime | None, bracket_id: UUID | None) -> list[_ScoreEvent]:
    """Solves and awards of ranked team members, as the team score counts them."""
    if not ids:
        return []
    member_filter = ranked_participant_q("participant__")
    if bracket_id is not None:
        member_filter &= Q(participant__bracket_id=bracket_id)
    solves = (
        _before(CTFSubmission.objects.filter(participant__team_id__in=ids, is_correct=True), "submitted_at", freeze_at)
        .filter(member_filter)
        .values_list("participant__team_id", "submitted_at", "challenge_id", "points_awarded")
    )
    awards = (
        _before(CTFAward.objects.filter(participant__team_id__in=ids), "created_at", freeze_at)
        .filter(member_filter)
        .values_list("participant__team_id", "created_at", "points")
    )
    events: list[_ScoreEvent] = [(str(tid), at, cid, pts) for tid, at, cid, pts in solves]
    events.extend((str(tid), at, None, pts) for tid, at, pts in awards)
    events.sort(key=lambda item: item[1])
    return events


def _before[QS: QuerySet[Any]](qs: QS, field: str, freeze_at: datetime | None) -> QS:
    """Apply the freeze cutoff the recompute scoreboard uses (strictly before)."""
    return qs.filter(**{f"{field}__lt": freeze_at}) if freeze_at else qs
