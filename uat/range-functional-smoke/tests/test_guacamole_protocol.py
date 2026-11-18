"""Guacamole display synchronization protocol tests (#1816)."""

from __future__ import annotations

import asyncio

import pytest

from range_functional_smoke.guacamole import (
    BrowserSynchronization,
    GuacamoleInstruction,
    GuacamoleInstructionParser,
    GuacamoleProtocolError,
    encode_instruction,
)
from range_functional_smoke.runner import Runner

_TUNNEL_ID = "00000000-0000-4000-8000-000000000001"


def test_parser_handles_fragmented_length_prefixed_instructions():
    parser = GuacamoleInstructionParser(max_buffer_bytes=128)

    assert parser.feed("5.rea") == []
    instructions = parser.feed("dy,3.abc;4.sync,3.123;")

    assert [(item.opcode, item.args) for item in instructions] == [
        ("ready", ("abc",)),
        ("sync", ("123",)),
    ]
    assert encode_instruction("sync", "123") == "4.sync,3.123;"


def test_parser_rejects_malformed_or_unbounded_streams():
    parser = GuacamoleInstructionParser(max_buffer_bytes=12)
    with pytest.raises(GuacamoleProtocolError):
        parser.feed("not-length-prefixed;")

    parser = GuacamoleInstructionParser(max_buffer_bytes=8)
    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("9.abcdefghi")


def test_parser_allows_a_large_batch_of_individually_bounded_instructions():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    instructions = parser.feed("1.a;1.b;1.c;")

    assert [item.opcode for item in instructions] == ["a", "b", "c"]


def test_parser_rejects_an_element_declared_larger_than_the_bound():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("9.")


def test_parser_rejects_non_ascii_digit_prefix_with_protocol_error():
    parser = GuacamoleInstructionParser(max_buffer_bytes=32)

    with pytest.raises(GuacamoleProtocolError, match="element length"):
        parser.feed("².foo;")


def test_parser_bounds_an_undelimited_slow_drip_length_prefix():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    assert parser.feed("1111") == []
    assert parser.feed("1111") == []
    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("1")


def test_browser_tunnel_identifier_is_a_valid_empty_opcode():
    parser = GuacamoleInstructionParser()
    instruction = parser.feed(encode_instruction("", _TUNNEL_ID))[0]
    probe = BrowserSynchronization()
    assert probe.observe(instruction) is None
    assert probe.tunnel_open and not probe.connected


def test_display_progress_requires_a_new_timestamp_after_the_first_acknowledgement():
    probe = BrowserSynchronization()
    probe.observe(GuacamoleInstruction("", (_TUNNEL_ID,)))
    assert probe.observe(GuacamoleInstruction("sync", ("100",))) == "4.sync,3.100;"
    assert not probe.connected
    probe.observe(GuacamoleInstruction("sync", ("100",)))
    assert not probe.connected
    assert probe.observe(GuacamoleInstruction("sync", ("101", "1"))) == "4.sync,3.101;"
    assert probe.connected


@pytest.mark.parametrize("args", [(), ("bad",), ("100", "bad"), ("100", "1", "2")])
def test_invalid_display_synchronization_is_refused(args):
    probe = BrowserSynchronization(tunnel_open=True)
    with pytest.raises(GuacamoleProtocolError, match="synchronization"):
        probe.observe(GuacamoleInstruction("sync", args))


def test_display_without_tunnel_identity_is_not_connected():
    with pytest.raises(GuacamoleProtocolError, match="synchronization"):
        BrowserSynchronization().observe(GuacamoleInstruction("sync", ("100",)))


@pytest.mark.parametrize("opcode,args", [("", ("bad-id",)), ("blob", ("bad-index", "data")), ("disconnect", ())])
def test_malformed_browser_identity_or_stream_and_disconnect_are_refused(opcode, args):
    with pytest.raises(GuacamoleProtocolError):
        BrowserSynchronization().observe(GuacamoleInstruction(opcode, args))


def test_image_payload_cannot_forge_ready_or_error_and_is_acknowledged():
    payload = "5.ready,36.fake;5.error,7.private,3.519;"
    instruction = GuacamoleInstructionParser().feed(encode_instruction("blob", "7", payload))[0]
    probe = BrowserSynchronization()
    assert probe.observe(instruction) == "3.ack,1.7,2.OK,1.0;"
    assert not probe.connected


class _BrowserTunnel:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []

    async def recv(self):
        try:
            frame, required_ack = next(self.frames)
        except StopIteration:
            raise ConnectionError("Synthetic tunnel ended") from None
        if required_ack is not None:
            assert required_ack in self.sent, "The browser must acknowledge the previous update"
        return frame

    async def send(self, frame):
        self.sent.append(frame)


def test_runner_handles_fragmentation_and_acknowledges_before_server_progress():
    tunnel = _BrowserTunnel(
        [
            (encode_instruction("", _TUNNEL_ID) + "4.sy", None),
            ("nc,3.100;", None),
            ("4.sync,3.101;", "4.sync,3.100;"),
        ]
    )
    assert asyncio.run(Runner._await_connected(tunnel)) is True
    assert tunnel.sent == ["4.sync,3.100;", "4.sync,3.101;"]


def test_runner_does_not_pass_a_tunnel_identifier_or_one_update():
    tunnel = _BrowserTunnel([(encode_instruction("", _TUNNEL_ID) + "4.sync,3.100;", None)])
    with pytest.raises(ConnectionError):
        asyncio.run(Runner._await_connected(tunnel))


def test_error_in_same_frame_as_progress_still_refuses_the_session():
    tunnel = _BrowserTunnel(
        [
            (encode_instruction("", _TUNNEL_ID) + "4.sync,3.100;", None),
            ("4.sync,3.101;" + encode_instruction("error", "private display data", "519"), "4.sync,3.100;"),
        ]
    )
    with pytest.raises(GuacamoleProtocolError) as caught:
        asyncio.run(Runner._await_connected(tunnel))
    assert "private display data" not in str(caught.value)
