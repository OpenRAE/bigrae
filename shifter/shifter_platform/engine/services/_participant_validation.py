"""Run one installed adapter's ``validate`` phase for experiment admission.

BigRAE never imports a backend's participant configuration owner. The ready
installation that declares the owner runs it in the isolated plugin worker.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID, uuid4

from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.validation import ParticipantValidation, ValidationInput, ValidationResult

from shared.cloud.runtime_plugins import interrupt_plugin, launch_plugin, observe_plugin

logger = logging.getLogger(__name__)

VALIDATION_TIMEOUT_SECONDS = 180
_POLL_SECONDS = 2.0


def _installation(organization_uuid: UUID, owner: str) -> Any:
    """Return the organization's one ready installation that declares the owner."""
    from engine.models import RuntimePluginInstallation

    rows = [
        row
        for row in RuntimePluginInstallation.objects.filter(
            organization_uuid=organization_uuid, state=RuntimePluginInstallation.State.READY
        )
        if owner in (row.manifest or {}).get("participant_validators", [])
    ]
    if len(rows) != 1:
        raise ValueError("Exactly one ready installation must validate this participant owner")
    return rows[0]


def validate_participant_configurations(
    organization_uuid: UUID, *, owner: str, family_digest: str, requests: list[dict[str, Any]]
) -> list[ParticipantValidation]:
    """Return the owner's result for each request, in order, or refuse."""
    from ._runtime_plugin_controller import _pull_secret

    row = _installation(organization_uuid, owner)
    manifest = PluginManifest.model_validate(row.manifest)
    if manifest.digest != row.manifest_digest:
        raise ValueError("Stored plugin identity mismatch")
    request = ValidationInput(
        protocol=manifest.protocol,
        invocation_id=uuid4(),
        phase="validate",
        manifest=manifest,
        owner=owner,
        family_digest=family_digest,
        requests=requests,
    )
    secret_name = f"runtime-plugin-pull-{request.invocation_id.hex}" if row.registry_credentials else ""
    launch_plugin(request, image_pull_secret=secret_name)
    _pull_secret(row, request)
    deadline = time.monotonic() + VALIDATION_TIMEOUT_SECONDS
    while (result := observe_plugin(request)) is None:
        if time.monotonic() >= deadline:
            interrupt_plugin(request)
            raise ValueError("Participant configuration validation timed out")
        time.sleep(_POLL_SECONDS)
    if not isinstance(result, ValidationResult) or result.status != "validated":
        logger.warning("participant validation refused installation_id=%s", row.pk)
        raise ValueError("The participant configuration owner refused the experiment configurations")
    return list(result.results)
