"""PostgreSQL proof that flag submissions and communication releases do not deadlock.

An event-wide communication release locks the event row and then inserts rows
that reference participants (foreign-key KEY SHARE locks). A submission locks
its participant row and then inserts rows that reference the event. Both sides
must take FOR NO KEY UPDATE locks, so that neither blocks the other's
foreign-key checks; FOR UPDATE on either side closed a lock cycle.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import close_old_connections, connection, transaction

from ctf.models import CTFAward, CTFEvent, CTFParticipant, CTFSubmission
from ctf.services.submission import submit_flag
from ctf.services.team import create_team
from tests.ctf.test_team_submission import FLAG, arena  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _run_with_lock_timeout(ready: Event, work):
    """Run ``work`` on a second connection that fails fast instead of waiting on a lock."""
    close_old_connections()
    try:
        assert ready.wait(10)
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '2s'")
        return work()
    finally:
        close_old_connections()


def test_submission_does_not_wait_on_the_release_event_lock(arena):  # noqa: F811
    event, player, challenge = arena
    create_team(player.pk, "Lock order team")
    locked = Event()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_with_lock_timeout, locked, lambda: submit_flag(player.pk, challenge.pk, FLAG))
        with transaction.atomic():
            # The same lock that release_campaign holds for its whole transaction.
            list(CTFEvent.objects.select_for_update(no_key=True).filter(pk=event.pk))
            locked.set()
            submission = future.result(timeout=20)

    assert submission.is_correct is True
    assert CTFSubmission.objects.filter(participant=player, challenge=challenge, is_correct=True).exists()


def test_participant_rows_stay_referenceable_while_a_submission_holds_them(arena):  # noqa: F811
    event, player, _challenge = arena
    locked = Event()

    def reference_participant():
        return CTFAward.objects.create(
            event=event, participant=player, points=0, reason="Lock order test", granted_by=event.created_by
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_with_lock_timeout, locked, reference_participant)
        with transaction.atomic():
            # The same participant lock that a flag submission holds.
            CTFParticipant.objects.select_for_update(no_key=True, of=("self",)).select_related("event").get(
                pk=player.pk
            )
            locked.set()
            award = future.result(timeout=20)

    assert CTFAward.objects.filter(pk=award.pk).exists()
