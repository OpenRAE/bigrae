"""Configured lifetime applied to every Guacamole participant session."""

from __future__ import annotations

from types import SimpleNamespace

from mission_control._guacamole_session_builders import (
    _generate_ngfw_ssh_url,
    _generate_range_ssh_url,
    _generate_rdp_url,
)


class _CapturingGuacamoleClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def create_rdp_url(self, request) -> str:
        self.requests.append(request)
        return "https://guacamole.example/client"

    def create_ssh_url(self, request) -> str:
        self.requests.append(request)
        return "https://guacamole.example/client"


def test_rdp_uses_configured_session_lifetime(settings):
    settings.GUACAMOLE_SESSION_TTL_MINUTES = 720
    client = _CapturingGuacamoleClient()

    _generate_rdp_url(
        username="participant",
        conn_info={"connection_name": "desktop", "private_ip": "192.0.2.10"},
        guac_client=client,
    )

    assert client.requests[0].expires_minutes == 720


def test_range_ssh_uses_configured_session_lifetime(settings):
    settings.GUACAMOLE_SESSION_TTL_MINUTES = 720
    client = _CapturingGuacamoleClient()

    _generate_range_ssh_url(
        username="participant",
        instance_uuid="instance-1",
        ssh_info={
            "connection_name": "shell",
            "host": "192.0.2.11",
            "port": 22,
            "username": "range-user",
            "private_key": "synthetic-private-key",
        },
        guac_client=client,
    )

    assert client.requests[0].expires_minutes == 720


def test_ngfw_ssh_uses_configured_session_lifetime(settings):
    settings.GUACAMOLE_SESSION_TTL_MINUTES = 720
    client = _CapturingGuacamoleClient()

    _generate_ngfw_ssh_url(
        username="participant",
        app_id="firewall-1",
        ssh_conn=SimpleNamespace(
            host="192.0.2.12",
            port=22,
            username="operator",
            private_key="synthetic-private-key",
        ),
        guac_client=client,
    )

    assert client.requests[0].expires_minutes == 720
