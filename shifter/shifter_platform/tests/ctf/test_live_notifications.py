"""Per-event live notifications (CTF-802, ADR-072, #665)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, LiveNotificationKind, ScheduledTaskType
from ctf.models import CommunicationCampaign, CTFChallenge, CTFParticipant, CTFScheduledTask, CTFTeam
from shared.models import WebSocketNotification

pytestmark = pytest.mark.django_db

ALL_KINDS = [kind.value for kind in LiveNotificationKind]


@pytest.fixture
def live_bus(settings):
    """Turn on the deployment capability for the test."""
    settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
    return settings


@pytest.fixture
def make_participant(django_user_model):
    """Register an active participant, optionally with a browser account."""

    def _make(event, name, *, with_user=True, team=None, score=0, minutes_ago=None):
        user = None
        if with_user:
            user = django_user_model.objects.create_user(username=f"{name}@test.com", email=f"{name}@test.com")
        participant = CTFParticipant.objects.create(
            event=event,
            user=user,
            email=f"{name}@test.com",
            name=name,
            status="active",
            registered_at=timezone.now(),
            team=team,
        )
        if score or minutes_ago is not None:
            CTFParticipant.objects.filter(pk=participant.pk).update(
                cached_score=score,
                last_solve_at=timezone.now() - timedelta(minutes=minutes_ago or 0),
            )
        return participant

    return _make


@pytest.fixture
def make_challenge():
    def _make(event, name="Synthetic", **extra):
        return CTFChallenge.objects.create(
            event=event,
            name=name,
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_format="FLAG{...}",
            **extra,
        )

    return _make


def _tasks(event, task_type):
    return CTFScheduledTask.objects.filter(event=event, task_type=task_type.value)


def _hint_rows(event, kind):
    return WebSocketNotification.objects.filter(topic=f"ctf:event:{event.pk}", payload={"kind": kind})


def _run_tasks(event, task_type):
    from ctf.services.notification.live import run_live_notice_task, run_position_reconcile_task

    runner = run_live_notice_task if task_type is ScheduledTaskType.LIVE_NOTICE else run_position_reconcile_task
    for task in _tasks(event, task_type).filter(status="pending"):
        runner(task)
        task.status = "completed"
        task.save(update_fields=["status", "updated_at"])


class TestEventSetting:
    def test_new_event_selects_all_kinds_and_rejects_unknown_or_duplicate(self, ctf_event_active):
        assert ctf_event_active.live_notifications == ALL_KINDS

        ctf_event_active.live_notifications = ["first_blood", "first_blood"]
        with pytest.raises(ValidationError):
            ctf_event_active.full_clean()
        ctf_event_active.live_notifications = ["unknown"]
        with pytest.raises(ValidationError):
            ctf_event_active.full_clean()

    def test_kind_requires_the_deployment_capability_and_the_event_choice(self, ctf_event_active, settings):
        from ctf.services.notification.live import effective_live_kinds, live_kind_enabled

        settings.WEBSOCKET_NOTIFICATIONS_ENABLED = False
        assert not live_kind_enabled(ctf_event_active, LiveNotificationKind.FIRST_BLOOD)
        assert effective_live_kinds(ctf_event_active) == []

        settings.WEBSOCKET_NOTIFICATIONS_ENABLED = True
        assert live_kind_enabled(ctf_event_active, LiveNotificationKind.FIRST_BLOOD)
        ctf_event_active.live_notifications = ["messages"]
        assert not live_kind_enabled(ctf_event_active, LiveNotificationKind.FIRST_BLOOD)
        assert effective_live_kinds(ctf_event_active) == ["messages"]


class TestZeroWork:
    def test_event_without_kinds_inserts_no_task_and_writes_no_row(
        self, live_bus, ctf_event_active, make_participant, make_challenge, monkeypatch
    ):
        from ctf.services import submit_flag
        from ctf.services.challenge import release_challenge

        ctf_event_active.live_notifications = []
        ctf_event_active.save(update_fields=["live_notifications", "updated_at"])
        challenge = make_challenge(ctf_event_active)
        hidden = make_challenge(ctf_event_active, name="Later", visibility="hidden")
        solver = make_participant(ctf_event_active, "solver")
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)

        submit_flag(solver.pk, challenge.pk, "FLAG{x}")
        release_challenge(hidden.pk)

        assert not CTFScheduledTask.objects.filter(
            task_type__in=[ScheduledTaskType.LIVE_NOTICE.value, ScheduledTaskType.RECONCILE_POSITIONS.value]
        ).exists()
        assert not WebSocketNotification.objects.exists()


class TestFirstBlood:
    def test_first_solve_declares_one_nameless_inbox_notice(
        self, live_bus, ctf_event_active, make_participant, make_challenge, monkeypatch
    ):
        from ctf.services import submit_flag

        challenge = make_challenge(ctf_event_active, name="Secret Chain Step")
        first = make_participant(ctf_event_active, "first-solver")
        second = make_participant(ctf_event_active, "second-solver")
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)

        submit_flag(first.pk, challenge.pk, "FLAG{x}")
        submit_flag(second.pk, challenge.pk, "FLAG{x}")

        notices = _tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE)
        assert [task.metadata for task in notices] == [{"notice": "first_blood", "challenge_id": str(challenge.pk)}]
        # Two solves coalesce onto one pending reconcile.
        assert _tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS).filter(status="pending").count() == 1

        _run_tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE)
        from ctf.services.notification.live import run_live_notice_task

        run_live_notice_task(notices.get())  # A retry collapses onto the first notice.

        campaign = CommunicationCampaign.objects.get(title="First blood")
        assert campaign.channels == ["in_app"]
        assert campaign.intents.count() == 1
        revision = campaign.message_revisions.get()
        for secret in ("Secret Chain Step", "first-solver", "second-solver"):
            assert secret not in revision.subject
            assert secret not in revision.body

    @pytest.mark.parametrize("board", ["hidden", "frozen"])
    def test_no_first_blood_while_board_is_hidden_or_frozen(
        self, board, live_bus, ctf_event_active, make_participant, make_challenge, monkeypatch
    ):
        from ctf.services import submit_flag

        if board == "hidden":
            ctf_event_active.scoreboard_visibility = "hidden"
        else:
            ctf_event_active.scoreboard_freeze_at = timezone.now() - timedelta(minutes=5)
        ctf_event_active.save()
        challenge = make_challenge(ctf_event_active)
        solver = make_participant(ctf_event_active, "solver")
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)

        submit_flag(solver.pk, challenge.pk, "FLAG{x}")

        assert not _tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE).exists()

    def test_queued_first_blood_is_dropped_when_the_board_freezes_before_it_runs(
        self, live_bus, ctf_event_active, make_participant, make_challenge, monkeypatch
    ):
        from ctf.services import submit_flag

        challenge = make_challenge(ctf_event_active)
        solver = make_participant(ctf_event_active, "solver")
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)
        submit_flag(solver.pk, challenge.pk, "FLAG{x}")
        assert _tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE).count() == 1

        # The organizer freezes the board at a cutoff before the solve, before the task runs.
        ctf_event_active.scoreboard_freeze_at = timezone.now() - timedelta(minutes=5)
        ctf_event_active.save()
        _run_tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE)

        assert not CommunicationCampaign.objects.filter(title="First blood").exists()


class TestChallengeRelease:
    def test_release_paths_declare_one_notice_while_the_event_runs(
        self, live_bus, ctf_event_active, make_participant, make_challenge
    ):
        from ctf.services.challenge import release_challenge, update_challenge

        make_participant(ctf_event_active, "watcher")
        scheduled = make_challenge(ctf_event_active, name="Scheduled", visibility="hidden")
        manual = make_challenge(ctf_event_active, name="Manual", visibility="hidden")

        release_challenge(scheduled.pk)
        release_challenge(scheduled.pk)  # Already visible: no second notice.
        update_challenge(manual.pk, {"visibility": "visible"}, actor_id=ctf_event_active.created_by_id)

        notices = _tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE)
        assert sorted(task.metadata["challenge_id"] for task in notices) == sorted([str(scheduled.pk), str(manual.pk)])
        assert {task.metadata["notice"] for task in notices} == {"challenge_released"}

        _run_tasks(ctf_event_active, ScheduledTaskType.LIVE_NOTICE)

        campaigns = CommunicationCampaign.objects.filter(title="New challenge available")
        assert campaigns.count() == 2
        assert all(c.channels == ["in_app"] and "Scheduled" not in c.message_revisions.get().body for c in campaigns)

    def test_release_before_the_event_runs_declares_nothing(self, live_bus, ctf_event, make_challenge):
        from ctf.services.challenge import release_challenge

        hidden = make_challenge(ctf_event, visibility="hidden")
        release_challenge(hidden.pk)
        assert not _tasks(ctf_event, ScheduledTaskType.LIVE_NOTICE).exists()


class TestPositionReconcile:
    def test_reconcile_hints_only_changed_entries_with_a_score(self, live_bus, ctf_event_active, make_participant):
        from ctf.services.notification.live import request_position_reconcile

        leader = make_participant(ctf_event_active, "leader", score=300, minutes_ago=30)
        chaser = make_participant(ctf_event_active, "chaser", score=200, minutes_ago=20)
        idle = make_participant(ctf_event_active, "idle")

        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)

        # The first assignment stores positions without a hint.
        assert dict(CTFParticipant.objects.values_list("name", "notified_position")) == {
            "leader": 1,
            "chaser": 2,
            "idle": 3,
        }
        assert not _hint_rows(ctf_event_active, "position_changed").exists()

        CTFParticipant.objects.filter(pk=chaser.pk).update(cached_score=400)
        CTFParticipant.objects.filter(pk=idle.pk).update(cached_score=0)
        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)

        hinted = set(_hint_rows(ctf_event_active, "position_changed").values_list("recipient_id", flat=True))
        assert hinted == {leader.user_id, chaser.user_id}

        # A reconcile with no rank change sends nothing.
        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)
        assert _hint_rows(ctf_event_active, "position_changed").count() == 2

    @pytest.mark.parametrize("board", ["hidden", "frozen"])
    def test_reconcile_does_nothing_while_board_is_hidden_or_frozen(
        self, board, live_bus, ctf_event_active, make_participant
    ):
        from ctf.services.notification.live import request_position_reconcile

        make_participant(ctf_event_active, "leader", score=300, minutes_ago=30)
        if board == "hidden":
            ctf_event_active.scoreboard_visibility = "hidden"
        else:
            ctf_event_active.scoreboard_freeze_at = timezone.now() - timedelta(minutes=5)
        ctf_event_active.save()

        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)

        assert list(CTFParticipant.objects.values_list("notified_position", flat=True)) == [None]

    def test_team_mode_hints_every_member_of_a_moved_team(self, live_bus, ctf_event_active, make_participant):
        from ctf.services.notification.live import request_position_reconcile

        ctf_event_active.team_mode = True
        ctf_event_active.team_size_limit = 4
        ctf_event_active.save()
        red = CTFTeam.objects.create(event=ctf_event_active, name="red")
        blue = CTFTeam.objects.create(event=ctf_event_active, name="blue")
        red_one = make_participant(ctf_event_active, "red-one", team=red)
        red_two = make_participant(ctf_event_active, "red-two", team=red)
        blue_one = make_participant(ctf_event_active, "blue-one", team=blue)
        now = timezone.now()
        CTFTeam.objects.filter(pk=red.pk).update(cached_score=100, last_solve_at=now - timedelta(minutes=9))
        CTFTeam.objects.filter(pk=blue.pk).update(cached_score=50, last_solve_at=now - timedelta(minutes=5))

        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)
        CTFTeam.objects.filter(pk=blue.pk).update(cached_score=500)
        request_position_reconcile(ctf_event_active.pk)
        _run_tasks(ctf_event_active, ScheduledTaskType.RECONCILE_POSITIONS)

        hinted = set(_hint_rows(ctf_event_active, "position_changed").values_list("recipient_id", flat=True))
        assert hinted == {red_one.user_id, red_two.user_id, blue_one.user_id}


class TestSocketProjection:
    def test_projection_admits_only_the_closed_shapes(self):
        from ctf.services.notification.realtime import _reference_payload

        ref = "00000000-0000-4000-8000-000000000001"
        assert _reference_payload({"kind": "position_changed", "name": "x"}) == {"kind": "position_changed"}
        assert _reference_payload({"kind": "range_ready", "secret": "x"}) == {"kind": "range_ready"}
        assert _reference_payload({"kind": "communication", "snapshot_id": ref, "intent_id": ref}) == {
            "kind": "communication",
            "snapshot_id": ref,
            "intent_id": ref,
        }
        assert _reference_payload({"kind": "first_blood", "challenge_name": "x"}) == {"kind": "refresh"}

    def test_range_ready_hints_keep_one_row_per_range_generation(self, live_bus, ctf_event_active, make_participant):
        from ctf.services.notification.realtime import publish_live_hint

        participant = make_participant(ctf_event_active, "racer")
        for generation in ("41", "42", "42"):
            publish_live_hint(
                ctf_event_active,
                LiveNotificationKind.RANGE_READY,
                recipient_ids=[participant.user_id],
                occurrence=f"{participant.pk}:{generation}",
            )
        assert _hint_rows(ctf_event_active, "range_ready").count() == 2


class TestInAppWakeup:
    def test_event_without_messages_kind_accepts_without_a_wakeup(self, live_bus, ctf_event_active, make_participant):
        import uuid

        from ctf.services.communication.adapters.contract import DeliveryCommand, OutcomeClass
        from ctf.services.communication.adapters.inapp import InAppAdapter

        ctf_event_active.live_notifications = ["first_blood"]
        ctf_event_active.save(update_fields=["live_notifications", "updated_at"])
        participant = make_participant(ctf_event_active, "reader")
        command = DeliveryCommand(
            attempt_id=uuid.uuid4(),
            intent_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            channel="in_app",
            event_id=ctf_event_active.pk,
            participant_public_id=None,
            recipient_user_id=participant.user_id,
            occurrence_key="notice",
            idempotency_key="synthetic",
        )

        outcome = InAppAdapter().deliver(command, timeout=1.0)

        assert outcome.outcome is OutcomeClass.ACCEPTED
        assert outcome.reason == "live_disabled"
        assert not WebSocketNotification.objects.exists()


class TestBoundedPrune:
    def test_prune_deletes_at_most_the_batch_budget(self, live_bus, ctf_event_active, make_participant):
        from ctf.services.notification.realtime import publish_live_hint
        from shared.notifications import prune_expired_notifications

        participant = make_participant(ctf_event_active, "pruned")
        for n in range(5):
            publish_live_hint(
                ctf_event_active,
                LiveNotificationKind.POSITION_CHANGED,
                recipient_ids=[participant.user_id],
                occurrence=str(n),
            )
        WebSocketNotification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        assert prune_expired_notifications(batch_size=2, max_batches=2) == 4
        assert WebSocketNotification.objects.count() == 1
        assert prune_expired_notifications(batch_size=2, max_batches=2) == 1


class TestEventApi:
    def test_organizer_sets_kinds_and_participant_reads_the_effective_list(
        self, live_bus, ctf_event_active, participant_user, authenticated_organizer_client
    ):
        from django.test import Client

        from management.services import set_active_ctf_event
        from tests.ctf._api_flow_helpers import call_json

        def put(body):
            return call_json(
                authenticated_organizer_client,
                "put",
                "api_event_detail",
                kwargs={"event_id": ctf_event_active.id},
                body=body,
            )

        assert put({"live_notifications": ["first_blood", "unknown"]}).status_code == 400
        assert put({"live_notifications": ["first_blood", "first_blood"]}).status_code == 400
        updated = put({"live_notifications": ["messages", "position_changed"]})
        assert updated.status_code == 200, updated.content
        detail = call_json(
            authenticated_organizer_client, "get", "api_event_detail", kwargs={"event_id": ctf_event_active.id}
        )
        assert detail.json()["live_notifications"] == ["messages", "position_changed"]

        CTFParticipant.objects.create(
            event=ctf_event_active, user=participant_user, name="reader", status="active", registered_at=timezone.now()
        )
        set_active_ctf_event(participant_user, ctf_event_active.pk)
        client = Client()
        client.force_login(participant_user)

        body = call_json(client, "get", "api_participant_current_event").json()
        assert body["event"]["live_notifications"] == ["messages", "position_changed"]

        live_bus.WEBSOCKET_NOTIFICATIONS_ENABLED = False
        body = call_json(client, "get", "api_participant_current_event").json()
        assert body["event"]["live_notifications"] == []


class TestSchedulerExecution:
    def test_scheduler_runs_live_notice_and_reconcile_tasks(
        self, live_bus, ctf_event_active, make_participant, make_challenge, monkeypatch
    ):
        from ctf.management.commands.run_ctf_scheduler import Command
        from ctf.services import submit_flag

        challenge = make_challenge(ctf_event_active)
        make_participant(ctf_event_active, "rival", score=50, minutes_ago=60)
        solver = make_participant(ctf_event_active, "solver")
        monkeypatch.setattr("ctf.services.submission.verify_flag", lambda _c, _f, **_kwargs: True)
        submit_flag(solver.pk, challenge.pk, "FLAG{x}")

        Command()._process_due_tasks(10)

        assert set(
            CTFScheduledTask.objects.filter(
                task_type__in=[ScheduledTaskType.LIVE_NOTICE.value, ScheduledTaskType.RECONCILE_POSITIONS.value]
            ).values_list("status", flat=True)
        ) == {"completed"}
        assert CommunicationCampaign.objects.filter(title="First blood").exists()
        assert CTFParticipant.objects.get(pk=solver.pk).notified_position == 1
