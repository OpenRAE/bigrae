"""Per-event live notifications (CTF-802, ADR-072).

Each event selects its live notification kinds. A kind is active only when the
deployment capability (``WEBSOCKET_NOTIFICATIONS_ENABLED``) is on and the event
lists the kind, so an event that selects nothing does no work.

Challenge release and first blood are durable inbox notices. The source
transaction inserts a ``LIVE_NOTICE`` scheduler task; the scheduler stages the
in-app ledger notice with fixed text that names no challenge and no participant.

A scoreboard position change is a content-free socket hint. Score owners insert
one pending ``RECONCILE_POSITIONS`` task per event; the scheduler compares the
participant-visible board with the stored notified positions under the event
lock and publishes hints after the commit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.enums import EventStatus, LiveNotificationKind, ScheduledTaskStatus, ScheduledTaskType

if TYPE_CHECKING:
    from ctf.models import CTFChallenge, CTFEvent, CTFParticipant, CTFScheduledTask, CTFTeam

logger = logging.getLogger(__name__)

_RUNNING = frozenset({EventStatus.ACTIVE.value, EventStatus.PAUSED.value})

# Fixed notice text. A challenge can have prerequisites, so no notice names it.
_NOTICE_TEXT: dict[LiveNotificationKind, tuple[str, str]] = {
    LiveNotificationKind.CHALLENGE_RELEASED: (
        "New challenge available",
        "A new challenge is available. Open the challenges page to see it.",
    ),
    LiveNotificationKind.FIRST_BLOOD: (
        "First blood",
        "A challenge has its first solve. Open the scoreboard for details.",
    ),
}


def live_kind_enabled(event: CTFEvent, kind: LiveNotificationKind | str) -> bool:
    """Return True when the deployment capability is on and the event selects ``kind``."""
    from shared.notifications import notifications_enabled

    return notifications_enabled() and LiveNotificationKind(kind).value in (event.live_notifications or [])


def effective_live_kinds(event: CTFEvent) -> list[str]:
    """Return the kinds the event publishes now; empty when the capability is off."""
    return [kind.value for kind in LiveNotificationKind if live_kind_enabled(event, kind)]


def event_selects(event_id: UUID, kind: LiveNotificationKind) -> bool:
    """Return True when the event row lists ``kind``; reads one column only."""
    from ctf.models import CTFEvent

    kinds = CTFEvent.objects.filter(pk=event_id).values_list("live_notifications", flat=True).first() or []
    return kind.value in kinds


def _board_open(event: CTFEvent) -> bool:
    """Participants can read live standings: the board is neither hidden nor frozen."""
    return event.scoreboard_visible and not event.is_scoreboard_frozen


def request_live_notice(event: CTFEvent, notice: LiveNotificationKind, challenge_id: UUID) -> None:
    """Insert one ``LIVE_NOTICE`` task in the caller's transaction, when the event uses it.

    First blood reveals a solve, so it is not declared while the board is hidden
    or frozen.
    """
    from ctf.models import CTFScheduledTask

    if notice not in _NOTICE_TEXT or not live_kind_enabled(event, notice):
        return
    if notice is LiveNotificationKind.FIRST_BLOOD and not _board_open(event):
        return
    CTFScheduledTask.objects.create(
        event_id=event.pk,
        task_type=ScheduledTaskType.LIVE_NOTICE.value,
        scheduled_for=timezone.now(),
        metadata={"notice": notice.value, "challenge_id": str(challenge_id)},
    )


def request_challenge_released(challenge: CTFChallenge, *, was_released: bool) -> None:
    """Declare a release notice when a write makes a challenge visible while the event runs."""
    if was_released or not challenge.is_released or challenge.event.status not in _RUNNING:
        return
    request_live_notice(challenge.event, LiveNotificationKind.CHALLENGE_RELEASED, challenge.pk)


def request_position_reconcile(event_id: UUID) -> None:
    """Make one pending position reconcile cover this change, when the event uses it.

    A score change calls this inside its own transaction. It updates the pending
    reconcile row, which locks the row until the caller commits. The scheduler
    claims with ``skip_locked``, so it cannot run that reconcile before this
    change commits. When no pending row matches (none exists, or the scheduler
    already claimed it), a new pending reconcile is inserted. A rare duplicate
    from a race is harmless: the second reconcile finds no change.
    """
    from ctf.models import CTFScheduledTask
    from shared.notifications import notifications_enabled

    if not notifications_enabled() or not event_selects(event_id, LiveNotificationKind.POSITION_CHANGED):
        return
    covered = CTFScheduledTask.objects.filter(
        event_id=event_id,
        task_type=ScheduledTaskType.RECONCILE_POSITIONS.value,
        status=ScheduledTaskStatus.PENDING.value,
    ).update(updated_at=timezone.now())
    if not covered:
        CTFScheduledTask.objects.create(
            event_id=event_id,
            task_type=ScheduledTaskType.RECONCILE_POSITIONS.value,
            scheduled_for=timezone.now(),
        )


def run_live_notice_task(task: CTFScheduledTask) -> None:
    """Stage the in-app ledger notice that a ``LIVE_NOTICE`` task names.

    The campaign identity derives from the event, the notice, and the challenge,
    so a retry or a second release collapses onto the first notice. A refused
    admission raises, so the task retries with its existing backoff.
    """
    from ctf.models import CTFEvent
    from ctf.services.notification.ledger import stage_notice

    metadata = task.metadata or {}
    notice = LiveNotificationKind(str(metadata.get("notice", "")))
    if notice not in _NOTICE_TEXT:
        raise ValueError("Unsupported live notice")
    challenge_id = UUID(str(metadata.get("challenge_id")))
    subject, body = _NOTICE_TEXT[notice]
    with transaction.atomic():
        # Hold the event lock from the check through staging, so a scoreboard
        # setting change (which also locks the event) cannot hide or freeze the
        # board between them. First blood reveals a solve: it needs an open board.
        event = CTFEvent.objects.select_for_update().get(pk=task.event_id)
        if not live_kind_enabled(event, notice):
            return
        if notice is LiveNotificationKind.FIRST_BLOOD and not _board_open(event):
            return
        stage_notice(
            event.pk,
            kind="announcement",
            subject=subject,
            body=body,
            occurrence=f"{notice.value}:{challenge_id}",
            channels=["in_app"],
        )


def run_position_reconcile_task(task: CTFScheduledTask) -> int:
    """Compare the visible board with the notified positions; hint moved entries.

    Returns the number of entries that received a hint. The publish runs after
    the transaction, so no transport work happens under the event lock.
    """
    from ctf.models import CTFEvent

    with transaction.atomic():
        event = CTFEvent.objects.select_for_update().filter(pk=task.event_id, deleted_at__isnull=True).first()
        if (
            event is None
            or event.status not in _RUNNING
            or not _board_open(event)
            or not live_kind_enabled(event, LiveNotificationKind.POSITION_CHANGED)
        ):
            return 0
        moved = _store_positions(event)
        recipients = _recipients(event, moved)

    from ctf.services.notification.realtime import publish_live_hint

    for entry_id, position in moved:
        publish_live_hint(
            event,
            LiveNotificationKind.POSITION_CHANGED,
            recipient_ids=recipients.get(entry_id, []),
            occurrence=f"{entry_id}:{position}:{task.pk}",
        )
    return len(moved)


def handle_live_notice_task(task: CTFScheduledTask, **_scheduler_hooks: object) -> None:
    """Scheduler entry point for ``LIVE_NOTICE``; it needs no shutdown or heartbeat hook."""
    run_live_notice_task(task)


def handle_position_reconcile_task(task: CTFScheduledTask, **_scheduler_hooks: object) -> None:
    """Scheduler entry point for ``RECONCILE_POSITIONS``; it needs no shutdown or heartbeat hook."""
    moved = run_position_reconcile_task(task)
    logger.info("RECONCILE_POSITIONS for event %s: moved=%d", task.event_id, moved)


def _store_positions(event: CTFEvent) -> list[tuple[UUID, int]]:
    """Write changed positions; return moved entries that have a score.

    An entry without a stored position gets one without a hint. An entry that
    left the board loses its stored position, so a return is a new assignment.
    """
    from ctf.models import CTFParticipant, CTFTeam
    from ctf.services.scoring import get_scoreboard, get_team_scoreboard

    if event.team_mode:
        return _store_board_positions(CTFTeam, "team_id", get_team_scoreboard(event.pk), event)
    return _store_board_positions(CTFParticipant, "participant_id", get_scoreboard(event.pk), event)


def _store_board_positions[Entry: (CTFParticipant, CTFTeam)](
    model: type[Entry], key: str, rows: Iterable[Mapping[str, Any]], event: CTFEvent
) -> list[tuple[UUID, int]]:
    """Diff one board against its model's notified positions; checked per entry model."""
    stored = dict(model.objects.filter(event=event).values_list("pk", "notified_position"))
    changed: list[Entry] = []
    moved: list[tuple[UUID, int]] = []
    ranked: set[UUID] = set()
    for row in rows:
        entry_id, position = UUID(row[key]), int(row["rank"])
        ranked.add(entry_id)
        previous = stored.get(entry_id)
        if previous == position:
            continue
        changed.append(model(pk=entry_id, notified_position=position))
        if previous is not None and row["score"] > 0:
            moved.append((entry_id, position))
    changed.extend(
        model(pk=entry_id, notified_position=None)
        for entry_id, previous in stored.items()
        if previous is not None and entry_id not in ranked
    )
    model.objects.bulk_update(changed, ["notified_position"], batch_size=500)
    return moved


def _recipients(event: CTFEvent, moved: list[tuple[UUID, int]]) -> dict[UUID, list[int]]:
    """Map each moved entry to the browser accounts of its viewing participants."""
    from ctf.models import CTFParticipant
    from ctf.services.participant import viewing_participant_q

    if not moved:
        return {}
    field = "team_id" if event.team_mode else "pk"
    entry_ids = [entry_id for entry_id, _position in moved]
    recipients: dict[UUID, list[int]] = {}
    rows = CTFParticipant.objects.filter(
        viewing_participant_q(), event=event, user_id__isnull=False, **{f"{field}__in": entry_ids}
    ).values_list(field, "user_id")
    for entry_id, user_id in rows:
        recipients.setdefault(entry_id, []).append(user_id)
    return recipients
