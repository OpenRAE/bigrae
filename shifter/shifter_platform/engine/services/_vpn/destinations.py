"""Resolve the private destinations that an OpenVPN session may reach."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.models import Range

_CHANNEL_PORTS = {"ssh": 22, "rdp": 3389}


_ACCESS_REVOKED = "vpn.access_revoked"


class VpnSessionDenied(ValueError):
    """The connection or request is refused with one closed reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VpnDestination:
    """One exact private destination and its declared participant ports."""

    target_ip: str
    ports: tuple[int, ...]


def _realized_member(range_obj: Range, target_ref: str) -> dict[str, object]:
    """Return the one realized RAES member named ``target_ref``."""
    members = range_obj.provisioned_instances if isinstance(range_obj.provisioned_instances, list) else []
    matches = [
        member
        for member in members
        if isinstance(member, dict) and member.get("uuid") == target_ref and member.get("role") == "raes-node"
    ]
    if len(matches) != 1:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    return matches[0]


def _channel_ports(channels: object) -> tuple[int, ...]:
    """Return the sorted ports of the declared participant channels."""
    if not isinstance(channels, list):
        return ()
    return tuple(sorted({_CHANNEL_PORTS[channel] for channel in channels if channel in _CHANNEL_PORTS}))


def _member_destination(range_obj: Range, target_ref: str) -> tuple[str, tuple[int, ...]]:
    """Resolve the realized participant target to one private address and its declared ports."""
    member = _realized_member(range_obj, target_ref)
    ports = _channel_ports(member.get("participant_access_channels"))
    try:
        address = ipaddress.ip_address(str(member.get("private_ip", "")))
    except ValueError as exc:
        raise VpnSessionDenied(_ACCESS_REVOKED) from exc
    if not ports or address.version != 4 or not address.is_private:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    return str(address), ports


def _member_destinations(range_obj: Range, target_refs: tuple[str, ...]) -> tuple[VpnDestination, ...]:
    """Resolve every authorized member without widening any member's ports."""
    return tuple(VpnDestination(*_member_destination(range_obj, target_ref)) for target_ref in target_refs)
