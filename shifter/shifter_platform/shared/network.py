"""Private IPv4 address-space boundaries for listeners and guest transports."""

from __future__ import annotations

import ipaddress

# RFC 1918 address-space boundaries, not deployment endpoints. S1313 review:
# these protocol constants must remain fixed to reject other special-use space.
RFC1918_IPV4_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),  # NOSONAR(S1313)
    ipaddress.IPv4Network("172.16.0.0/12"),  # NOSONAR(S1313)
    ipaddress.IPv4Network("192.168.0.0/16"),  # NOSONAR(S1313)
)


def private_listener_address(value: str) -> str:
    """Bind only the explicit private pod address supplied by deployment readback."""
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in RFC1918_IPV4_NETWORKS):
        raise ValueError("listener requires an explicit private IPv4 address")
    return str(address)
