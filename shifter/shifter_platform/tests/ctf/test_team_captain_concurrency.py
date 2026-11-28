"""PostgreSQL proof that dissolution and a real solve overlap on member locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from ctf.exceptions import CTFNotFoundError, CTFStateError
from ctf.models import CTFParticipant, CTFSubmission, CTFTeam
from ctf.services.submission import submit_flag
from ctf.services.team import create_team, disband_team, join_team, regenerate_invite_code
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
                # #3000: a disband that commits first leaves the captain teamless,
                # so the serialized submission scores them as an individual.
                submission = submit_flag(captain.pk, challenge.pk, FLAG)
                assert submission.is_correct is True
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
    # solve_first: disband is refused while the solve is open, so the team survives.
    # disband-first: the team is soft-deleted. The captain scores a correct solve in
    # both orders (the second as an individual, #3000).
    assert CTFTeam.objects.filter(pk=team.pk).exists() is solve_first
    assert CTFSubmission.objects.filter(participant=captain, is_correct=True).exists()


def _register_joiner(event, django_user_model, label):
    """An eligible, registered participant in ``event`` ready to join a team."""
    user = django_user_model.objects.create_user(username=f"{label}@test.com", email=f"{label}@test.com")
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=user.email,
        name=label.title(),
        status="active",
        registered_at=timezone.now(),
    )


def test_single_use_redemption_rechecks_after_lock(arena, django_user_model):  # noqa: F811
    """CTF-504: a spend committed between a join's lookup and its lock yields 404.

    The worker looks up a valid single-use code, member-locks, then blocks on the
    team row lock the main thread holds. The main thread spends the code and
    commits. The worker then reads the spent row and is rejected. This fails if
    code validity is checked before the lock instead of from the locked row.
    """
    event, captain, _challenge = arena
    team = create_team(captain.pk, "Recheck")
    regenerate_invite_code(captain.pk, single_use=True)
    team.refresh_from_db()
    code = team.invite_code

    joiner = _register_joiner(event, django_user_model, "racer")
    connected = Event()
    worker_pids: list[int] = []
    outcome: dict[str, str] = {}

    def contender():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pids.append(cursor.fetchone()[0])
            connected.set()
            try:
                join_team(joiner.pk, code)
                outcome["result"] = "joined"
            except CTFNotFoundError:
                outcome["result"] = "invalid"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            # Hold only the team row. The worker member-locks (NOWAIT) without
            # conflict, then blocks here on the team lock after its lookup.
            CTFTeam.objects.select_for_update().get(pk=team.pk)
            future = pool.submit(contender)
            assert connected.wait(10)
            _wait_for_database_block(worker_pids[0])
            # Spend the single-use code while the worker waits for the team lock.
            CTFTeam.objects.filter(pk=team.pk).update(invite_code_spent=True)
        future.result(timeout=20)

    assert outcome["result"] == "invalid"
    joiner.refresh_from_db()
    assert joiner.team_id is None
    assert CTFParticipant.objects.filter(team=team).count() == 1
