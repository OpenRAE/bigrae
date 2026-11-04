"""Pinned SSH transport shared by authorized participant and provisioner probes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import asyncssh


class GuestProbeError(Exception):
    """Raised when the in-guest probe transport fails."""


@dataclass(frozen=True)
class GuestProbeRequest:
    """The cohesive connection + payload inputs for one in-guest probe run."""

    host: str
    username: str
    private_key: str = field(repr=False)
    host_public_key: str
    command: str
    stdin: str = field(repr=False)
    port: int = 22
    timeout_s: int = 30
    max_output_bytes: int | None = None


def run_guest_probe(request: GuestProbeRequest) -> str:
    """Run the probe command in a range guest over SSH, returning stdout.

    ``request.command`` is the delivery wrapper (``bash -s`` for a native VM, or
    ``docker exec -i <container> bash -s`` for a scenario container) and
    ``request.stdin`` the self-contained probe program. ``request.host_public_key``
    is the guest's OpenSSH public key from platform provisioning state; it is pinned
    so an impostor server cannot return a forged all-secure envelope. A missing host
    key, a nonzero remote exit, or any transport error raises :class:`GuestProbeError`
    so the gate treats a probe that did not verifiably run as a failure, never a pass.
    """
    if not request.host_public_key.strip():
        raise GuestProbeError(
            f"missing guest host identity for {request.host}:{request.port}; refusing unverified probe"
        )
    return asyncio.run(_timed_guest_probe(request))


async def _timed_guest_probe(request: GuestProbeRequest) -> str:
    """Bound connection establishment and command execution together."""
    try:
        return await asyncio.wait_for(_run_guest_probe(request), timeout=request.timeout_s)
    except TimeoutError:
        raise GuestProbeError("guest probe timed out") from None


async def _run_guest_probe(request: GuestProbeRequest) -> str:
    """Open a host-key-pinned SSH session and run the probe command, returning stdout."""
    try:
        key = asyncssh.import_private_key(request.private_key)
        host = request.host if request.port == 22 else f"[{request.host}]:{request.port}"
        known_hosts = asyncssh.import_known_hosts(f"{host} {request.host_public_key.strip()}\n")
        async with asyncssh.connect(
            request.host,
            port=request.port,
            username=request.username,
            client_keys=[key],
            known_hosts=known_hosts,
            connect_timeout=request.timeout_s,
        ) as conn:
            if request.max_output_bytes is not None:
                return await asyncio.wait_for(_bounded_probe(conn, request), timeout=request.timeout_s)
            result = await conn.run(request.command, input=request.stdin, timeout=request.timeout_s)
    except (asyncssh.Error, OSError, ValueError) as exc:
        # OSError already covers TimeoutError (the asyncssh command timeout).
        raise GuestProbeError(f"in-guest probe transport failed for {request.host}:{request.port}") from exc
    if result.exit_status not in (0, None):
        raise GuestProbeError(f"in-guest probe exited {result.exit_status} for {request.host}:{request.port}")
    return result.stdout if isinstance(result.stdout, str) else ""


async def _bounded_probe(conn: asyncssh.SSHClientConnection, request: GuestProbeRequest) -> str:
    """Bound both streams before buffering output from an untrusted guest."""
    limit = request.max_output_bytes
    if type(limit) is not int or not 1 <= limit <= 1048576:
        raise GuestProbeError("invalid guest output bound")
    process = await conn.create_process(request.command)
    try:
        process.stdin.write(request.stdin)
        process.stdin.write_eof()
        stdout, _ = await asyncio.gather(
            _read_bounded_stream(process.stdout, limit), _read_bounded_stream(process.stderr, limit)
        )
        await process.wait_closed()
        if process.exit_status != 0:
            raise GuestProbeError("guest probe failed")
        return stdout
    finally:
        process.close()


async def _read_bounded_stream(stream: asyncssh.SSHReader[str], limit: int) -> str:
    """Stop before an untrusted stream can exceed its byte allowance."""
    chunks: list[str] = []
    size = 0
    while True:
        part = await stream.read(limit + 1 - size)
        if not part:
            return "".join(chunks)
        size += len(part.encode())
        if size > limit:
            raise GuestProbeError("guest output exceeds its bound")
        chunks.append(part)
