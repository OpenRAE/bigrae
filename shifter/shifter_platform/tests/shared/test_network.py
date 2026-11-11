"""Private listeners bind only explicit RFC 1918 IPv4 addresses."""

import ipaddress

import pytest

from shared.network import private_listener_address


@pytest.mark.parametrize("address", ["10.1.2.3", "172.16.0.9", "172.31.255.254", "192.168.4.5"])
def test_private_listener_accepts_rfc1918_addresses(address):
    assert private_listener_address(address) == address


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        str(ipaddress.IPv4Address(0)),
        "127.0.0.1",
        "100.64.0.1",
        "169.254.169.254",
        "172.32.0.1",
        "fd00::1",
        "10.0.0.0/8",
    ],
)
def test_private_listener_rejects_public_and_other_special_use_addresses(address):
    with pytest.raises(ValueError):
        private_listener_address(address)
