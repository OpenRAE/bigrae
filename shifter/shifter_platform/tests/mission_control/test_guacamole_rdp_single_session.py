"""A new RDP session ends the same principal's earlier RDP session for the same target."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class _Gateway:
    """Record native session terminations; optionally fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.terminated: list[str] = []

    def terminate_session(self, token: str) -> bool:
        if self.fail:
            raise RuntimeError("synthetic gateway failure")
        self.terminated.append(token)
        return True


@pytest.fixture
def gateway(monkeypatch):
    client = _Gateway()
    monkeypatch.setattr("mission_control.guacamole_session._bind_guacamole_client", lambda *a, **k: client)
    return client


def _row(*, principal, target, protocol="rdp", target_id="provision.node.training-host#0", age=60, token=None):
    from mission_control.models import GuacamoleBootstrapRequest

    row = GuacamoleBootstrapRequest.objects.create(
        protocol=protocol,
        target_id=target_id,
        status=GuacamoleBootstrapRequest.Status.SUCCEEDED,
        expires_at=timezone.now() + timedelta(minutes=5),
        authority_kind="principal",
        authority_target_uuid=target,
        initiating_principal_uuid=principal,
        native_session_token=token or f"token-{uuid4().hex}",
    )
    GuacamoleBootstrapRequest.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(seconds=age))
    row.refresh_from_db()
    return row


def test_second_rdp_start_ends_the_first_native_session(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    principal, target = uuid4(), uuid4()
    first = _row(principal=principal, target=target, age=120, token="first-token")
    second = _row(principal=principal, target=target, age=5, token="second-token")

    assert end_previous_rdp_sessions(second.pk) == 1

    first.refresh_from_db()
    second.refresh_from_db()
    assert gateway.terminated == ["first-token"]
    assert first.native_terminated_at is not None
    assert first.native_session_token == ""
    assert second.native_terminated_at is None
    assert second.native_session_token == "second-token"


def test_ssh_sessions_are_untouched(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    principal, target = uuid4(), uuid4()
    ssh = _row(principal=principal, target=target, protocol="range_ssh", age=120)
    rdp = _row(principal=principal, target=target, age=5)

    assert end_previous_rdp_sessions(rdp.pk) == 0
    ssh.refresh_from_db()
    assert ssh.native_terminated_at is None
    assert gateway.terminated == []


def test_new_ssh_start_ends_nothing(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    principal, target = uuid4(), uuid4()
    earlier_ssh = _row(principal=principal, target=target, protocol="range_ssh", age=120)
    new_ssh = _row(principal=principal, target=target, protocol="range_ssh", age=5)

    assert end_previous_rdp_sessions(new_ssh.pk) == 0
    earlier_ssh.refresh_from_db()
    assert earlier_ssh.native_terminated_at is None
    assert gateway.terminated == []


def test_another_target_rdp_session_is_untouched(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    principal = uuid4()
    other_range = _row(principal=principal, target=uuid4(), age=120)
    other_host = _row(principal=principal, target=uuid4(), target_id="provision.node.other-host#0", age=110)
    current = _row(principal=principal, target=uuid4(), age=5)

    assert end_previous_rdp_sessions(current.pk) == 0
    for row in (other_range, other_host):
        row.refresh_from_db()
        assert row.native_terminated_at is None
    assert gateway.terminated == []


def test_another_principal_session_is_untouched(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    target = uuid4()
    someone_else = _row(principal=uuid4(), target=target, age=120)
    current = _row(principal=uuid4(), target=target, age=5)

    assert end_previous_rdp_sessions(current.pk) == 0
    someone_else.refresh_from_db()
    assert someone_else.native_terminated_at is None
    assert gateway.terminated == []


def test_a_later_session_is_never_ended_by_an_earlier_one(gateway):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    principal, target = uuid4(), uuid4()
    earlier = _row(principal=principal, target=target, age=120)
    later = _row(principal=principal, target=target, age=5)

    assert end_previous_rdp_sessions(earlier.pk) == 0
    later.refresh_from_db()
    assert later.native_terminated_at is None


def test_gateway_failure_does_not_raise(monkeypatch, caplog):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    failing = _Gateway(fail=True)
    monkeypatch.setattr("mission_control.guacamole_session._bind_guacamole_client", lambda *a, **k: failing)
    principal, target = uuid4(), uuid4()
    first = _row(principal=principal, target=target, age=120, token="first-token")
    second = _row(principal=principal, target=target, age=5)

    assert end_previous_rdp_sessions(second.pk) == 0
    assert "Previous RDP session not ended" in caplog.text
    assert "first-token" not in caplog.text
    first.refresh_from_db()
    assert first.native_terminated_at is None


def test_unavailable_gateway_configuration_does_not_raise(monkeypatch, caplog):
    from mission_control.guacamole_bootstrap import end_previous_rdp_sessions

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic configuration failure")

    monkeypatch.setattr("mission_control.guacamole_session._bind_guacamole_client", unavailable)
    principal, target = uuid4(), uuid4()
    _row(principal=principal, target=target, age=120)
    second = _row(principal=principal, target=target, age=5)

    assert end_previous_rdp_sessions(second.pk) == 0
    assert "Previous RDP session lookup failed" in caplog.text


def test_delivery_ends_previous_rdp_session(monkeypatch):
    from mission_control import guacamole_bootstrap

    calls = []
    monkeypatch.setattr(guacamole_bootstrap, "_delivery_actor", lambda request_id, credential: object())
    monkeypatch.setattr(guacamole_bootstrap, "_consume_admitted_url", lambda request_id, admitted: "https://url")
    monkeypatch.setattr(guacamole_bootstrap, "end_previous_rdp_sessions", lambda request_id: calls.append(request_id))
    request_id = uuid4()

    assert guacamole_bootstrap.consume_ready_url(request_id=request_id, credential=object()) == "https://url"
    assert calls == [request_id]


def test_refused_delivery_ends_nothing(monkeypatch):
    from mission_control import guacamole_bootstrap

    calls = []
    monkeypatch.setattr(guacamole_bootstrap, "_delivery_actor", lambda request_id, credential: object())
    monkeypatch.setattr(guacamole_bootstrap, "_consume_admitted_url", lambda request_id, admitted: None)
    monkeypatch.setattr(guacamole_bootstrap, "end_previous_rdp_sessions", lambda request_id: calls.append(request_id))

    assert guacamole_bootstrap.consume_ready_url(request_id=uuid4(), credential=object()) is None
    assert calls == []
