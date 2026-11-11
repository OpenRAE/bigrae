"""Run one installed adapter's ``validate`` phase for experiment admission.

BigRAE never imports a backend's participant configuration owner. The ready
installation that declares the owner runs it in the isolated plugin worker.
Admission records the request; the plugin launcher, the only identity that
creates plugin Jobs, runs the worker and records its authorized result.
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.utils import timezone
from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.validation import (
    ParticipantValidation,
    ParticipantValidationRequest,
    ValidationInput,
    ValidationResult,
)

from shared.cloud.runtime_plugins import interrupt_plugin, launch_plugin, observe_plugin

if TYPE_CHECKING:
    from engine.models import RuntimePluginInstallation, RuntimePluginValidation

logger = logging.getLogger(__name__)

VALIDATION_TIMEOUT_SECONDS = 300
_POLL_SECONDS = 2.0


def _installation(organization_uuid: UUID, owner: str) -> RuntimePluginInstallation:
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


def _request(
    row: RuntimePluginInstallation, owner: str, family_digest: str, requests: list[dict[str, Any]]
) -> ValidationInput:
    """Build the exact validate input bound to the installation's stored identity."""
    manifest = PluginManifest.model_validate(row.manifest)
    if manifest.digest != row.manifest_digest:
        raise ValueError("Stored plugin identity mismatch")
    return ValidationInput(
        protocol="bigrae.runtime-plugin/v2",
        invocation_id=uuid4(),
        phase="validate",
        manifest=manifest,
        owner=owner,
        family_digest=family_digest,
        requests=[ParticipantValidationRequest.model_validate(item) for item in requests],
    )


def validate_participant_configurations(
    organization_uuid: UUID, *, owner: str, family_digest: str, requests: list[dict[str, Any]]
) -> list[ParticipantValidation]:
    """Record one validate request, await the launcher's result, and return it in order or refuse."""
    from engine.models import RuntimePluginValidation

    installation = _installation(organization_uuid, owner)
    request = _request(installation, owner, family_digest, requests)
    row = RuntimePluginValidation.objects.create(
        id=request.invocation_id,
        installation=installation,
        input=request.model_dump(mode="json"),
        expires_at=timezone.now() + timedelta(seconds=VALIDATION_TIMEOUT_SECONDS),
    )
    deadline = time.monotonic() + VALIDATION_TIMEOUT_SECONDS + 30
    while row.state == "pending":
        if time.monotonic() >= deadline:
            raise ValueError("Participant configuration validation timed out")
        time.sleep(_POLL_SECONDS)
        row.refresh_from_db(fields=["state", "result"])
    if row.state != "validated":
        logger.warning("participant validation refused installation_id=%s", installation.pk)
        raise ValueError("The participant configuration owner refused the experiment configurations")
    return list(ValidationResult.model_validate(row.result).results)


def reconcile_participant_validations(*, limit: int = 3) -> int:
    """Run a bounded batch of pending validate requests in isolated plugin workers."""
    from engine.models import RuntimePluginValidation

    if not 1 <= limit <= 30:
        raise ValueError("Invalid validation reconciliation batch size")
    rows = list(RuntimePluginValidation.objects.filter(state="pending").order_by("created_at", "id")[:limit])
    for row in rows:
        _reconcile(row)
    return len(rows)


def _reconcile(row: RuntimePluginValidation) -> None:
    """Launch or observe one worker; record only a result authorized for its input."""
    from engine.models import RuntimePluginValidation

    from ._runtime_plugin_controller import _pull_secret

    state, result, request = "pending", None, None
    try:
        request = ValidationInput.model_validate(row.input)
        if row.expires_at <= timezone.now():
            raise ValueError("Participant configuration validation expired")
        secret_name = (
            f"runtime-plugin-pull-{request.invocation_id.hex}" if row.installation.registry_credentials else ""
        )
        launch_plugin(request, image_pull_secret=secret_name)
        _pull_secret(row.installation, request)
        observed = observe_plugin(request)
        if observed is not None:
            if not isinstance(observed, ValidationResult):
                raise ValueError("Invalid validation result")
            observed.authorize(request)
            state = "validated" if observed.status == "validated" else "failed"
            result = observed.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001  # plugin and registry errors can carry private output; log the type only
        state, result = "failed", None
        logger.warning("participant validation failed validation_id=%s exc_type=%s", row.pk, type(exc).__name__)
        if request is not None:
            # The Job deadline still bounds execution if interruption is unavailable.
            with suppress(Exception):
                interrupt_plugin(request)
    if state != "pending":
        RuntimePluginValidation.objects.filter(pk=row.pk, state="pending").update(
            state=state, result=result, updated_at=timezone.now()
        )
