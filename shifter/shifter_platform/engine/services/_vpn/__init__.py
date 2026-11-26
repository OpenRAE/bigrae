"""VPN profile access, certificate operations, delivery, PKI results and session leases.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .profile_access import VpnProfileConflict as VpnProfileConflict
from .profile_access import VpnProfileNotFound as VpnProfileNotFound
from .profile_access import VpnProfilePending as VpnProfilePending
from .profile_access import VpnProfileUnavailable as VpnProfileUnavailable
from .profile_access import get_openvpn_profile as get_openvpn_profile
from .profile_access import has_openvpn_profile as has_openvpn_profile
from .profiles import get_vpn_crl as get_vpn_crl
from .sessions import VPN_SESSION_HEARTBEAT_SECONDS as VPN_SESSION_HEARTBEAT_SECONDS
from .sessions import VPN_SESSION_LEASE_SECONDS as VPN_SESSION_LEASE_SECONDS
from .sessions import VpnSessionDenied as VpnSessionDenied
from .sessions import VpnSessionGrant as VpnSessionGrant
from .sessions import authorize_vpn_session as authorize_vpn_session
from .sessions import end_vpn_session as end_vpn_session
from .sessions import renew_vpn_sessions as renew_vpn_sessions

__all__ = [
    "VPN_SESSION_HEARTBEAT_SECONDS",
    "VPN_SESSION_LEASE_SECONDS",
    "VpnProfileConflict",
    "VpnProfileNotFound",
    "VpnProfilePending",
    "VpnProfileUnavailable",
    "VpnSessionDenied",
    "VpnSessionGrant",
    "authorize_vpn_session",
    "end_vpn_session",
    "get_openvpn_profile",
    "get_vpn_crl",
    "has_openvpn_profile",
    "renew_vpn_sessions",
]
