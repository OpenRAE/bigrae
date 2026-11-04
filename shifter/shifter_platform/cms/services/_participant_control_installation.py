"""The fixed native implementation must match the current admitted deployment."""

from django.conf import settings

from shared.exceptions import ValidationError
from shared.participant_control_installation import NativeControlInstallation


def require_native_control_installation(expected_digest: str | None = None) -> NativeControlInstallation:
    """Check local installation pins without remote calls or executable selection."""
    installed = settings.PARTICIPANT_CONTROL_INSTALLATION
    if (
        not isinstance(installed, NativeControlInstallation)
        or installed.provisioner_image != str(settings.ENGINE_TASK_DEFINITION)
        or (expected_digest is not None and installed.digest != expected_digest)
    ):
        raise ValidationError("Native participant control installation unavailable")
    return installed


def require_native_control_policy(expected_digest: str) -> NativeControlInstallation:
    """A compatible restart may change transport; persisted control policy cannot drift."""
    installed = require_native_control_installation()
    if installed.policy_digest != expected_digest:
        raise ValidationError("Native participant control policy changed")
    return installed
