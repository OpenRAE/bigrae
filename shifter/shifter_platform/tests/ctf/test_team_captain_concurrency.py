"""PostgreSQL proof that dissolution and a real solve overlap on member locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import close_old_connections, connection, transaction

from ctf.exceptions import CTFStateError
from ctf.models import CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.submission import submit_flag
from ctf.services.team import create_team, disband_team
from tests.ctf.test_team_submission import FLAG, arena  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _wait_for_database_block(worker_pid: int) -> None:
    """Observe an actual PostgreSQL lock wait, rather than a thread start."""
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = %s",
                [worker_pid],
            )
            row = cursor.fetchone()
            cursor.execute("SELECT pg_backend_pid()")
            own_pid = cursor.fetchone()[0]
        if row and row[0] == "Lock" and own_pid in row[1]:
            return
        sleep(0.01)
    pytest.fail("Submission did not block on the uncommitted dissolution")


@pytest.mark.parametrize("solve_first", [True, False])
def test_solve_and_disband_serialize(arena, solve_first):  # noqa: F811
    _event, captain, challenge = arena
    team = create_team(captain.pk, "Serialized team")
    connected = Event()
    worker_pids = []

    def contender():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pids.append(cursor.fetchone()[0])
            connected.set()
            if solve_first:
                with pytest.raises(CTFStateError, match="busy"):
                    disband_team(captain.pk)
            else:
                with pytest.raises(CTFStateError, match="team"):
                    submit_flag(captain.pk, challenge.pk, FLAG)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            CTFParticipant.objects.select_for_update().get(pk=captain.pk)
            if solve_first:
                submit_flag(captain.pk, challenge.pk, FLAG)
            else:
                disband_team(captain.pk)
            future = pool.submit(contender)
            assert connected.wait(10)
            if solve_first:
                # NOWAIT must refuse while the solve remains uncommitted.
                future.result(timeout=10)
            else:
                # The submission loaded old membership and now waits for our row.
                _wait_for_database_block(worker_pids[0])
        future.result(timeout=20)
    assert CTFTeam.objects.filter(pk=team.pk).exists() is solve_first
    assert CTFSubmission.objects.filter(participant=captain, is_correct=True).exists() is solve_first
