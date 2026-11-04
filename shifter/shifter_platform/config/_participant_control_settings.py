"""Fail-closed, installation-owned configuration for the persistent native controller."""

import os

from django.core.exceptions import ImproperlyConfigured

from shared.model_access.messages import strict_json
from shared.participant_control_installation import NativeControlInstallation

__all__ = [
    "PARTICIPANT_CONTROL_ENABLED",
    "PARTICIPANT_CONTROL_INSTALLATION",
    "PARTICIPANT_CONTROL_OWNER_PROCESS",
]


def _boolean(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ImproperlyConfigured("Participant control flags require true or false")
    return value == "true"


def load_native_control_installation(
    raw: str,
    *,
    enabled: bool,
    owner_process: bool,
) -> NativeControlInstallation | None:
    """Bound input and suppress private pasted material in startup diagnostics."""
    try:
        installed = NativeControlInstallation.model_validate(strict_json(raw.encode(), limit=32_768)) if raw else None
        if (enabled and installed is None) or (owner_process and not enabled):
            raise ValueError
        return installed
    except Exception:  # noqa: BLE001  # never echo an invalid installation body into process logs
        raise ImproperlyConfigured("Participant control installation is unavailable or invalid") from None


PARTICIPANT_CONTROL_ENABLED = _boolean(os.environ.get("PARTICIPANT_CONTROL_ENABLED", "false"))
PARTICIPANT_CONTROL_OWNER_PROCESS = _boolean(os.environ.get("PARTICIPANT_CONTROL_OWNER_PROCESS", "false"))
PARTICIPANT_CONTROL_INSTALLATION = load_native_control_installation(
    os.environ.get("PARTICIPANT_CONTROL_CONFIGURATION", ""),
    enabled=PARTICIPANT_CONTROL_ENABLED,
    owner_process=PARTICIPANT_CONTROL_OWNER_PROCESS,
)
