"""Process-local composition seam for the separately installed persistent worker."""

from django.conf import settings

from cms.services._participant_control_installation import require_native_control_installation
from cms.services._participant_control_registry import NativeParticipantControlRegistry
from shared.native_participant import NativeControlUnavailable

_registry: NativeParticipantControlRegistry | None = None


def install_participant_control_registry(registry: NativeParticipantControlRegistry) -> None:
    """Only fixed worker startup calls this after verifying its installation and Pod."""
    global _registry
    if (
        not settings.PARTICIPANT_CONTROL_ENABLED
        or not settings.PARTICIPANT_CONTROL_OWNER_PROCESS
        or not isinstance(registry, NativeParticipantControlRegistry)
        or _registry is not None
    ):
        raise NativeControlUnavailable("Participant control worker unavailable")
    require_native_control_installation()
    _registry = registry


def participant_control_registry() -> NativeParticipantControlRegistry:
    """Portal requests cannot create ephemeral owners or activate a worker."""
    if (
        not settings.PARTICIPANT_CONTROL_ENABLED
        or not settings.PARTICIPANT_CONTROL_OWNER_PROCESS
        or _registry is None
        or _registry.draining
    ):
        raise NativeControlUnavailable("Participant control worker unavailable")
    return _registry


def begin_participant_control_drain() -> None:
    """Stop new leases while retaining active owners and unresolved calls."""
    if _registry is not None:
        _registry.begin_drain()


def close_participant_control_registry() -> None:
    """Retain the registry if native or SDK calls have not yet drained."""
    global _registry
    if _registry is not None:
        _registry.close()
        _registry = None
