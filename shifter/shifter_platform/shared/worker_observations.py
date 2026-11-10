"""Closed, credential-free host observations from the native provisioner."""

import json
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Fingerprint = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class WorkerHardware(BaseModel):
    """Provider-reported settings of the realized host, recorded exactly as read."""

    model_config = ConfigDict(extra="forbid", strict=True)

    machine_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
    enable_secure_boot: bool
    # Empty means the provider reports no explicit interface type.
    nic_type: Annotated[str, Field(pattern=r"^[A-Z_]{0,32}$")]
    disk_interface: Annotated[str, Field(pattern=r"^[A-Z_]{0,32}$")]
    image_id: Annotated[str, Field(pattern=r"^[1-9]\d{0,19}$")]


class WorkerHostObservation(BaseModel):
    """One fixed probe's safe facts, without raw provider or guest identities."""

    model_config = ConfigDict(extra="forbid", strict=True)

    vm_identity: Fingerprint
    machine_identity: Fingerprint
    daemon_identity: Fingerprint
    docker_version: Annotated[str, Field(pattern=r"^[0-9][A-Za-z0-9.+-]{0,63}$")]
    daemon_count: Annotated[int, Field(strict=True, ge=1, le=1)]
    hardware: WorkerHardware
    observed_at: AwareDatetime


def validate_worker_observations(value: object) -> dict[str, dict[str, Any]]:
    """Validate bounded exact-member observations on both sides of the result bus."""
    if not isinstance(value, dict) or len(value) > 64:
        raise ValueError("Worker observations are invalid")
    result = {}
    for target, observation in value.items():
        if not isinstance(target, str) or not 1 <= len(target) <= 1024:
            raise ValueError("Worker observation target is invalid")
        # JSON-mode validation accepts an ISO timestamp while retaining strict
        # integer/string checks and refusing additional fields.
        try:
            parsed = WorkerHostObservation.model_validate_json(json.dumps(observation))
        except (ValueError, TypeError):
            raise ValueError("Worker observations are invalid") from None
        result[target] = parsed.model_dump(mode="json")
    return result


def require_fresh_observation(observation: dict[str, Any], now: datetime) -> None:
    """Never treat an old or future guest observation as current qualification."""
    observed = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
    if not now - timedelta(seconds=900) <= observed <= now + timedelta(seconds=5):
        raise ValueError("Worker observation has expired")
