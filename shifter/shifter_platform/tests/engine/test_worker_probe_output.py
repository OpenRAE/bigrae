"""Untrusted guest output is bounded across transport chunks, including stderr."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncssh
import pytest

from engine.services import GuestProbeError, GuestProbeRequest, run_guest_probe


@pytest.mark.parametrize("chunks,expected", [(["ab", "cd", ""], "abcd"), (["ab", "cde", ""], None)])
def test_probe_reads_to_eof_and_refuses_overflow(monkeypatch, chunks, expected):
    key = asyncssh.generate_private_key("ssh-ed25519")
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=chunks)),
        stderr=SimpleNamespace(read=AsyncMock(return_value="")),
        stdin=SimpleNamespace(write=lambda value: None, write_eof=lambda: None),
        wait_closed=AsyncMock(),
        exit_status=0,
        close=lambda: None,
    )

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create_process(self, command):
            return process

    monkeypatch.setattr(asyncssh, "connect", lambda *args, **kwargs: Connection())
    request = GuestProbeRequest(
        host="10.0.0.2",
        username="management",
        private_key=key.export_private_key().decode(),
        host_public_key=key.export_public_key().decode(),
        command="fixed",
        stdin="",
        max_output_bytes=4,
    )
    if expected is None:
        with pytest.raises(GuestProbeError):
            run_guest_probe(request)
    else:
        assert run_guest_probe(request) == expected
