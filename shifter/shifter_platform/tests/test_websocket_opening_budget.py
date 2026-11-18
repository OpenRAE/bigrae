"""Exercise the configured WebSocket transport over a synthetic loopback socket."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import InvalidStatus
from websockets.frames import Frame, Opcode

from config import asgi_worker
from config.asgi_worker import ShifterUvicornWorker


@asynccontextmanager
async def _serve(application, **overrides):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        config = uvicorn.Config(
            application,
            lifespan="off",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=1,
            **{**ShifterUvicornWorker.CONFIG_KWARGS, **overrides},
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            yield f"ws://127.0.0.1:{listener.getsockname()[1]}/"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=5)


def test_delayed_valid_acceptance_exchanges_frames():
    """Application admission may take longer than the library's default ten seconds."""

    async def exercise():
        async def application(scope, receive, send):
            assert scope["type"] == "websocket"
            assert (await receive())["type"] == "websocket.connect"
            await asyncio.sleep(11)
            await send({"type": "websocket.accept"})
            message = await receive()
            assert message["text"] == "synthetic-probe"
            await send({"type": "websocket.send", "text": "synthetic-reply"})
            await send({"type": "websocket.close", "code": 1000})

        async with (
            _serve(application) as url,
            websockets.connect(url, open_timeout=15, proxy=None) as connection,
        ):
            await connection.send("synthetic-probe")
            assert await connection.recv() == "synthetic-reply"

    asyncio.run(exercise())


def test_unaccepted_handshake_has_a_finite_enforced_deadline(monkeypatch):
    assert asgi_worker._WS_OPEN_TIMEOUT_SECONDS == 30.0
    monkeypatch.setattr(asgi_worker, "_WS_OPEN_TIMEOUT_SECONDS", 0.05)

    async def exercise():
        async def application(scope, receive, send):
            assert (await receive())["type"] == "websocket.connect"
            assert (await receive())["type"] == "websocket.disconnect"

        async with _serve(application) as url:
            with pytest.raises(InvalidStatus) as refused:
                async with websockets.connect(url, open_timeout=1, proxy=None):
                    pytest.fail("A pending handshake must not become an accepted session")
            assert refused.value.response.status_code == 500

    asyncio.run(exercise())


def test_connected_socket_survives_opening_deadline_and_retains_server_keepalive(monkeypatch):
    monkeypatch.setattr(asgi_worker, "_WS_OPEN_TIMEOUT_SECONDS", 0.05)

    class PingConnection(ClientConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pings = 0
            self.keepalive_seen = asyncio.Event()

        def process_event(self, event):
            if isinstance(event, Frame) and event.opcode == Opcode.PING:
                self.pings += 1
                if self.pings >= 3:
                    self.keepalive_seen.set()
            super().process_event(event)

    async def exercise():
        async def application(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            assert (await receive())["type"] == "websocket.disconnect"

        async with (
            _serve(application, ws_ping_interval=0.03, ws_ping_timeout=0.5) as url,
            websockets.connect(url, proxy=None, create_connection=PingConnection) as connection,
        ):
            await asyncio.wait_for(connection.keepalive_seen.wait(), timeout=1)

    asyncio.run(exercise())
