"""The Guacamole bootstrap prune worker reports liveness during a long cycle."""

from types import SimpleNamespace
from unittest import mock

import pytest

from mission_control import guacamole_authority
from mission_control.management.commands import run_guacamole_bootstrap_prune as prune_command


class _Rows(list):
    """Stand-in for the bounded revalidation queryset."""

    def exclude(self, **_kwargs):
        return self

    def order_by(self, *_args):
        return self


def test_revalidation_reports_progress_once_per_session():
    rows = _Rows(
        SimpleNamespace(pk=index, delivered_at=None, is_expired=False, termination_pending=True) for index in range(3)
    )
    progress = mock.Mock()
    manager = SimpleNamespace(filter=lambda **_kwargs: rows)
    with (
        mock.patch("mission_control.models.GuacamoleBootstrapRequest.objects", manager),
        mock.patch.object(guacamole_authority, "terminate_bootstrap", return_value=False) as terminate,
    ):
        guacamole_authority.revalidate_guacamole_sessions(client=mock.Mock(), limit=10, progress=progress)

    assert progress.call_count == 3
    assert terminate.call_count == 3


def test_revalidation_without_progress_still_runs():
    rows = _Rows([SimpleNamespace(pk=1, delivered_at=None, is_expired=False, termination_pending=True)])
    manager = SimpleNamespace(filter=lambda **_kwargs: rows)
    with (
        mock.patch("mission_control.models.GuacamoleBootstrapRequest.objects", manager),
        mock.patch.object(guacamole_authority, "terminate_bootstrap", return_value=True),
    ):
        assert guacamole_authority.revalidate_guacamole_sessions(client=mock.Mock(), limit=10) == 1


def test_prune_cycle_refreshes_heartbeat_during_revalidation_and_each_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(prune_command, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    command = prune_command.Command()
    touches = mock.Mock()
    monkeypatch.setattr(command, "_touch_heartbeat", touches)
    with (
        mock.patch.object(prune_command, "revalidate_guacamole_sessions") as revalidate,
        mock.patch.object(prune_command, "prune_expired_bootstrap_requests", side_effect=[5, 5, 2]),
    ):
        assert command._prune_cycle(batch_size=5) == 12

    assert revalidate.call_args.kwargs["progress"] is touches
    assert touches.call_count == 3


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
