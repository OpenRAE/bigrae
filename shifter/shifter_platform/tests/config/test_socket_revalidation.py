"""Idle transport revocation must reach the consumer's real cleanup path."""

import asyncio
from time import monotonic

import pytest
from channels.testing import ApplicationCommunicator

from config.websocket_auth import CredentialSessionWebSocketBoundary


@pytest.mark.asyncio
async def test_idle_logout_closes_default_boundary_without_a_client_message(monkeypatch, settings):
    """Regression against the existing default session boundary, with no new port."""
    live = True
    settings.IDENTITY_SESSION_RECHECK_SECONDS = 0.02
    monkeypatch.setattr("config.session_credentials.validate_socket_session", lambda scope, **kwargs: live)
    cleaned_up = asyncio.Event()

    async def application(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        try:
            assert (await receive())["type"] == "websocket.disconnect"
        finally:
            cleaned_up.set()

    communicator = ApplicationCommunicator(CredentialSessionWebSocketBoundary(application), {})
    try:
        await communicator.send_input({"type": "websocket.connect"})
        assert await communicator.receive_output() == {"type": "websocket.accept"}
        live = False
        assert await communicator.receive_output(timeout=0.3) == {"type": "websocket.close", "code": 4001}
        await communicator.wait(timeout=0.3)
        assert cleaned_up.is_set()
    finally:
        communicator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["deny", "outage", "timeout"])
async def test_idle_socket_revocation_disconnects_consumer_and_cancels_watcher(monkeypatch, failure):
    from config import session_credentials

    monkeypatch.setattr(session_credentials, "validate_socket_session", lambda scope, **kwargs: True)
    revoked = asyncio.Event()
    cleanup = asyncio.Event()
    checks = []

    async def authority(scope):
        checks.append(monotonic())
        if not revoked.is_set():
            return True
        if failure == "outage":
            raise ConnectionError("policy unavailable")
        if failure == "timeout":
            await asyncio.Event().wait()
        return False

    async def application(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        try:
            message = await receive()
            assert message["type"] == "websocket.disconnect"
        finally:
            cleanup.set()

    boundary = CredentialSessionWebSocketBoundary(
        application, resource_authorizer=authority, recheck_seconds=0.02, timeout_seconds=0.02
    )
    communicator = ApplicationCommunicator(boundary, {})
    await communicator.send_input({"type": "websocket.connect"})
    assert await communicator.receive_output() == {"type": "websocket.accept"}
    started = monotonic()
    revoked.set()
    assert await communicator.receive_output(timeout=0.3) == {"type": "websocket.close", "code": 4001}
    await communicator.wait(timeout=0.3)
    assert cleanup.is_set()
    assert monotonic() - started < 0.3
    count = len(checks)
    await asyncio.sleep(0.05)
    assert len(checks) == count


@pytest.mark.asyncio
async def test_protected_output_and_privileged_input_recheck_before_delivery(monkeypatch):
    from config import session_credentials

    monkeypatch.setattr(session_credentials, "validate_socket_session", lambda scope, **kwargs: True)
    live = True
    received = []

    async def authority(scope):
        return live

    async def application(scope, receive, send):
        nonlocal live
        await receive()
        await send({"type": "websocket.accept"})
        live = False
        await send({"type": "websocket.send", "text": "protected output"})
        received.append(await receive())

    boundary = CredentialSessionWebSocketBoundary(application, resource_authorizer=authority)
    communicator = ApplicationCommunicator(boundary, {})
    await communicator.send_input({"type": "websocket.connect"})
    assert await communicator.receive_output() == {"type": "websocket.accept"}
    assert await communicator.receive_output() == {"type": "websocket.close", "code": 4001}
    await communicator.wait()
    assert received == [{"type": "websocket.disconnect", "code": 4001}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,override,expected",
    [
        ("/ws/terminal/00000000-0000-4000-8000-000000000001/", None, 15.0),
        ("/ws/notifications/", None, 5.0),
        ("/ws/terminal/not-a-target/", None, 5.0),
        ("/ws/terminal/00000000-0000-4000-8000-000000000001/", 0.25, 0.25),
    ],
)
async def test_complete_authority_checks_use_the_route_budget_for_open_input_and_output(
    monkeypatch, path, override, expected
):
    monkeypatch.setattr("config.session_credentials.validate_socket_session", lambda scope, **kwargs: True)
    deadlines = []
    real_timeout = asyncio.timeout

    def timed_check(delay):
        deadlines.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr("config.websocket_auth.asyncio.timeout", timed_check)

    async def authority(scope):
        return True

    async def application(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        incoming = await receive()
        assert incoming["type"] == "websocket.receive"
        await send({"type": "websocket.send", "text": "protected output"})

    boundary = CredentialSessionWebSocketBoundary(application, resource_authorizer=authority, timeout_seconds=override)
    communicator = ApplicationCommunicator(boundary, {"path": path})
    try:
        await communicator.send_input({"type": "websocket.connect"})
        assert await communicator.receive_output() == {"type": "websocket.accept"}
        await communicator.send_input({"type": "websocket.receive", "text": "input"})
        assert await communicator.receive_output() == {"type": "websocket.send", "text": "protected output"}
        await communicator.wait()
        # The periodic watcher has its own interval timeout. Opening, input,
        # and output must each use the route authority budget.
        assert deadlines.count(expected) >= 3
    finally:
        communicator.stop()
