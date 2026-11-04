"""Bounded administrator-owned apparatus, distinct from experiment content."""

from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from shifter_adapter_sdk.runtime import ClosedModel, Digest, canonical_digest

from shared.raes.worker_host import worker_host_shape
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimeTargetImageProfile


class WorkerSoftwareBinding(ClosedModel):
    """An operator selects an already installed, exact executable version."""

    installation_id: UUID
    organization_uuid: UUID
    manifest_digest: Digest
    bindings: PluginTargetBindings


class WorkerHostProfile(ClosedModel):
    """One independently provisioned outer host; no inner SDL or executable input."""

    plan: dict[str, Any]
    image: RuntimeTargetImageProfile
    image_id: Annotated[str, Field(pattern=r"^[1-9]\d{0,19}$")]
    provenance_digest: Digest
    docker_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.]+)?$")]
    capacity_scope_ref: UUID
    capacity_partition: Annotated[str, Field(min_length=1, max_length=128)]
    capacity_demand: dict[str, Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(min_length=1, max_length=32)
    egress_mode: Literal["none", "status-quo"] = "none"
    software: WorkerSoftwareBinding | None = None

    @model_validator(mode="after")
    def validate_host(self) -> Self:
        """Reject ambiguous topology and mutable or undersized apparatus inputs."""
        _, _, _, cpu, ram = worker_host_shape(self.plan)
        _validate_worker_image(self.image)
        # The incumbent GCE realizer derives e2-custom from the plan when the
        # image profile has no override. Keep quota demand and physical size in
        # agreement, including its 256 MiB alignment, before any effects.
        if cpu not in range(2, 33, 2) or ram % (256 * 1024**2) or not cpu * 512 * 1024**2 <= ram <= cpu * 8 * 1024**3:
            raise ValueError("Worker resources require a supported E2 custom shape")
        if self.capacity_demand.get("vcpu", 0) < cpu or self.capacity_demand.get("instances", 0) < 1:
            raise ValueError("Worker capacity demand does not cover its host")
        if len(self.model_dump_json().encode()) > 131072:
            raise ValueError("Worker profile exceeds its bound")
        return self

    @property
    def digest(self) -> str:
        """Identify the exact admitted apparatus snapshot."""
        return canonical_digest(self.model_dump(mode="json"))


class WorkerPolicy(ClosedModel):
    """Global limits are published by the operator, never chosen by a launch."""

    profile: WorkerHostProfile
    max_live: Annotated[int, Field(strict=True, ge=1, le=1000)]
    max_provisioning: Annotated[int, Field(strict=True, ge=1, le=100)]
    lifetime_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)] = 3600
    recovery_attempts: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    hold_review_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)] = 86400

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        """Keep provisioning concurrency within the global live bound."""
        if self.max_provisioning > self.max_live:
            raise ValueError("Worker concurrency exceeds live capacity")
        return self


def _validate_worker_image(image: RuntimeTargetImageProfile) -> None:
    """Accept only an exact standard GCE host without resource or egress overrides."""
    if (
        image.provider != "gcp"
        or image.image_kind != "image"
        or image.bootstrap_capability != "standard"
        or image.machine_type
        or image.disk_size_gb is None
        or not image.management_ssh_username
        or image.allow_public_web_egress
    ):
        raise ValueError("Worker host requires an exact standard GCE image profile")
