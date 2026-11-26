"""The Guacamole bootstrap prune worker reports liveness during a long cycle."""

import urllib.error
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from mission_control import guacamole_authority
from mission_control.management.commands import run_guacamole_bootstrap_prune as prune_command
from mission_control.models import GuacamoleBootstrapRequest

pytestmark = [pytest.mark.django_db]


class _Gateway:
    """Synthetic native gateway that records each termination request."""

    def __init__(self, *, terminated: bool) -> None:
        self.terminated = terminated
        self.tokens: list[str] = []

    def terminate_session(self, token: str) -> bool:
        self.tokens.append(token)
        return self.terminated


def _pending_termination(index: int) -> GuacamoleBootstrapRequest:
    """A principal session already marked for termination, so no reauthorization runs."""
    return GuacamoleBootstrapRequest.objects.create(
        protocol="range_ssh",
        target_id=f"synthetic-target-{index}",
        expires_at=timezone.now() + timedelta(hours=1),
        authority_kind="principal",
        native_session_token=f"synthetic-token-{index}",
        termination_pending=True,
    )


def _expired_prunable(index: int) -> GuacamoleBootstrapRequest:
    return GuacamoleBootstrapRequest.objects.create(
        protocol="range_ssh",
        target_id=f"synthetic-expired-{index}",
        expires_at=timezone.now() - timedelta(minutes=5),
    )


def test_revalidation_reports_progress_once_per_session():
    for index in range(3):
        _pending_termination(index)
    gateway = _Gateway(terminated=False)
    progress = mock.Mock()

    terminated = guacamole_authority.revalidate_guacamole_sessions(client=gateway, limit=10, progress=progress)

    assert terminated == 0
    assert progress.call_count == 3
    assert sorted(gateway.tokens) == [f"synthetic-token-{index}" for index in range(3)]


def test_revalidation_without_progress_still_runs():
    row = _pending_termination(0)

    assert guacamole_authority.revalidate_guacamole_sessions(client=_Gateway(terminated=True), limit=10) == 1

    row.refresh_from_db()
    assert row.native_terminated_at is not None
    assert row.native_session_token == ""


def test_prune_cycle_refreshes_heartbeat_during_revalidation_and_each_batch(tmp_path, monkeypatch, settings):
    settings.GUACAMOLE_API_BASE_URL = "https://guacamole.example.test"
    monkeypatch.setattr(prune_command, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    pending = _pending_termination(0)
    for index in range(12):
        _expired_prunable(index)
    command = prune_command.Command()
    touches = mock.Mock()
    monkeypatch.setattr(command, "_touch_heartbeat", touches)

    # The gateway is unreachable, so the session stays pending for the next cycle.
    with mock.patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError("synthetic outage")):
        assert command._prune_cycle(batch_size=5) == 12

    # One touch for the revalidated session, then one for each batch of 5, 5 and 2.
    assert touches.call_count == 4
    assert list(GuacamoleBootstrapRequest.objects.values_list("pk", flat=True)) == [pending.pk]


@pytest.mark.parametrize("poll_interval", [1, 90])
def test_worker_writes_heartbeat_before_its_first_cycle(tmp_path, monkeypatch, poll_interval):
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setattr(prune_command, "HEARTBEAT_FILE", heartbeat)
    command = prune_command.Command()
    seen_before_cycle = []

    def first_cycle(_batch_size):
        seen_before_cycle.append(heartbeat.exists())
        command.shutdown = True
        return 0

    monkeypatch.setattr(command, "_prune_cycle", first_cycle)
    monkeypatch.setattr(prune_command.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(prune_command, "close_old_connections", lambda: None)
    command.handle(poll_interval=poll_interval, batch_size=10)

    assert seen_before_cycle == [True]
