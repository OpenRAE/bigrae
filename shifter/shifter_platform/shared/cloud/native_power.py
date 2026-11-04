"""Read-only provider proof for one already consumed native call permission."""

from typing import Protocol

from shared.native_participant import NativePowerInvocationGrant


class NativePowerObserver(Protocol):
    """Observe original provider-call cessation without issuing a mutation."""

    def completed_call(self, grant: NativePowerInvocationGrant) -> str | None:
        """Return an exact completed operation reference, or retain uncertainty."""
        ...
