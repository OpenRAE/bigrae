"""PostgreSQL proof that a coalesced position reconcile waits for its source commit (ADR-072-R3).

SQLite cannot prove row locks or ``skip_locked`` claiming, so this runs only on the
Postgres lane. It drives the real scheduler claim against a real source transaction.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, transaction

from ctf.enums import ScheduledTaskType
from ctf.models import CTFScheduledTask

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _claim_in_another_connection():
    from ctf.management.commands.run_ctf_scheduler import Command

    def claim():
        try:
            claimed = Command()._claim_next_due()
            return None if claimed is None else claimed[0].task_type
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(claim).result(timeout=30)


def _reconciles(event):
    return CTFScheduledTask.objects.filter(event=event, task_type=ScheduledTaskType.RECONCILE_POSITIONS.value)


def test_pending_reconcile_cannot_be_claimed_before_the_covering_change_commits(ctf_event_active, settings):
    from ctf.services.notification.live import request_position_reconcile

    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
    request_position_reconcile(ctf_event_active.pk)
    assert _reconciles(ctf_event_active).filter(status="pending").count() == 1

    with transaction.atomic():
        # A later score change coalesces onto the pending row and holds it.
        request_position_reconcile(ctf_event_active.pk)
        assert _claim_in_another_connection() is None

    assert _claim_in_another_connection() == ScheduledTaskType.RECONCILE_POSITIONS.value


def test_change_after_the_claim_queues_a_new_reconcile(ctf_event_active, settings):
    from ctf.services.notification.live import request_position_reconcile

    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
    request_position_reconcile(ctf_event_active.pk)
    assert _claim_in_another_connection() == ScheduledTaskType.RECONCILE_POSITIONS.value

    request_position_reconcile(ctf_event_active.pk)

    assert set(_reconciles(ctf_event_active).values_list("status", flat=True)) == {"running", "pending"}
