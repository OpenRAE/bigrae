"""Single-process TLS worker for the installed persistent participant owner."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import stat
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from asgiref.sync import sync_to_async

from shared.model_access.http import ASGIScope, Receive, Send

logger = logging.getLogger(__name__)


@contextmanager
def installation_owner_lock(root: Path) -> Iterator[None]:
    """Exclude another process without replacing the released per-store owner."""
    root.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Participant owner storage is not private")
    descriptor = os.open(root / ".installation-owner", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Participant owner lock is not private")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


class ParticipantControlApplication:
    """Dedicated Django HTTP application with explicit drain and health endpoints."""

    def __init__(self, application: Callable[[ASGIScope, Receive, Send], Awaitable[None]]) -> None:
        self._application = application
        self.draining = False
        self._recovery_stop = asyncio.Event()
        self._recovery_task: asyncio.Task[None] | None = None

    def begin_drain(self) -> None:
        """Stop admission and signal the retained recovery loop to drain."""
        from cms.participant_control_runtime import begin_participant_control_drain

        self.draining = True
        self._recovery_stop.set()
        begin_participant_control_drain()

    async def _recover_calls(self) -> None:
        cursor = None
        while not self._recovery_stop.is_set():
            try:
                cursor = await sync_to_async(_recover_one_call, thread_sensitive=False)(cursor)
            except Exception as exc:  # noqa: BLE001  # failures retain durable exclusions; expose no backend diagnostic
                logger.warning("Participant call recovery unavailable exc_type=%s", type(exc).__name__)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._recovery_stop.wait(), timeout=5)

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        """Serve fixed health, lifespan, and authenticated HTTP boundaries."""
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http" and scope["path"] in {"/health/live", "/health/ready"}:
            ready = scope["path"] == "/health/live" or (not self.draining and await sync_to_async(_ready)())
            await send({"type": "http.response.start", "status": 200 if ready else 503, "headers": []})
            await send({"type": "http.response.body", "body": b"ok" if ready else b"unavailable"})
        elif scope["type"] == "http":
            await self._application(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        from cms.participant_control_runtime import close_participant_control_registry

        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self._recovery_task = asyncio.create_task(self._recover_calls())
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                self.begin_drain()
                try:
                    if self._recovery_task is not None:
                        await self._recovery_task
                    await sync_to_async(close_participant_control_registry)()
                except Exception as exc:  # noqa: BLE001  # an unresolved call retains native exclusion after exit
                    logger.error("Participant owner drain incomplete exc_type=%s", type(exc).__name__)
                    await send({"type": "lifespan.shutdown.failed", "message": "Participant owner drain incomplete"})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return


def _recover_one_call(cursor: UUID | None) -> UUID | None:
    """Keep one bounded recovery call and its DB connection outside HTTP threads."""
    from django.db import connections

    from engine.services import reconcile_native_power_invocations

    try:
        return reconcile_native_power_invocations(cursor=cursor, limit=1).cursor
    finally:
        connections.close_all()


def _ready() -> bool:
    from django.db import connection

    from cms.participant_control_runtime import participant_control_registry
    from cms.services._participant_control_installation import require_native_control_installation

    try:
        participant_control_registry()
        require_native_control_installation()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except Exception:  # noqa: BLE001  # a failed dependency is unreadiness, never a backend disclosure
        return False


def main() -> None:
    """Start the fixed worker while keeping installation diagnostics private."""
    from shared.model_access.diagnostics import isolate_transport_diagnostics

    isolate_transport_diagnostics()
    try:
        _main()
    except Exception:  # noqa: BLE001  # configuration and identity errors may contain private deployment material
        raise SystemExit("Participant control worker unavailable") from None


def _main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    import uvicorn
    from django.conf import settings
    from django.core.asgi import get_asgi_application

    from cms.participant_control_runtime import install_participant_control_registry
    from cms.participant_control_worker_identity import installed_owner_address
    from cms.services._participant_control_installation import require_native_control_installation
    from cms.services._participant_control_registry import NativeParticipantControlRegistry
    from shared.cloud import get_task_runner
    from shared.cloud.kubernetes import KubernetesTaskRunner

    installation = require_native_control_installation()
    if not settings.PARTICIPANT_CONTROL_OWNER_PROCESS:
        raise ValueError("Participant owner process is disabled")
    if settings.CLOUD_PROVIDER != "gcp" or not isinstance(get_task_runner(), KubernetesTaskRunner):
        raise ValueError("Participant owner installation requires the selected GCE Job runtime")
    address = installed_owner_address(installation)
    settings.ROOT_URLCONF = "config.participant_control_worker_urls"
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, urlsplit(installation.control_origin).hostname, address]
    with installation_owner_lock(installation.store_root):
        install_participant_control_registry(NativeParticipantControlRegistry(installation))
        handler = get_asgi_application()

        async def http(scope: ASGIScope, receive: Receive, send: Send) -> None:
            async def send_mapping(message: Mapping[str, Any]) -> None:
                await send(dict(message))

            await handler(scope, receive, send_mapping)

        application = ParticipantControlApplication(http)

        class DrainingServer(uvicorn.Server):
            def handle_exit(self, sig: int, frame: FrameType | None) -> None:
                application.begin_drain()
                super().handle_exit(sig, frame)

        DrainingServer(
            uvicorn.Config(
                application,
                host=address,
                port=8445,
                workers=1,
                lifespan="on",
                ws="none",
                ssl_certfile="/etc/shifter/participant-control/tls/tls.crt",
                ssl_keyfile="/etc/shifter/participant-control/tls/tls.key",
                proxy_headers=False,
                forwarded_allow_ips="",
                access_log=False,
                server_header=False,
                timeout_graceful_shutdown=45,
                limit_concurrency=64,
                h11_max_incomplete_event_size=16_384,
            )
        ).run()


if __name__ == "__main__":
    main()
