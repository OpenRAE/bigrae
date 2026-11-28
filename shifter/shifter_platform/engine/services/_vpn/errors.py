"""OpenVPN profile delivery errors."""

from __future__ import annotations


class VpnProfileNotFound(ValueError):
    """No owned range exists for the requested correlation id."""


class VpnProfileConflict(ValueError):
    """The range exists but its current lifecycle cannot deliver a profile."""


class VpnProfileUnavailable(ValueError):
    """The provider binding or secret is unavailable or invalid."""


class VpnProfilePending(VpnProfileConflict):
    """The original credential's individual profile is being prepared."""
