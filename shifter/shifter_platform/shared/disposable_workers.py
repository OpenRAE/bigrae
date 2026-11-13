"""Bounded administrator-owned apparatus, distinct from experiment content."""

import re
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from shifter_adapter_sdk.runtime import ClosedModel, Digest, canonical_digest

from shared.raes.worker_host import worker_host_shape
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimeTargetImageProfile

# A predefined machine type states its vCPU count, for example c4a-standard-4.
_PREDEFINED_MACHINE = re.compile(r"^[a-z][a-z0-9]*-(?:standard|highcpu|highmem)-([1-9]\d{0,2})$")


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
        # Keep quota demand and physical size in agreement before any effects.
        # A predefined machine type must state the plan's vCPU count. Otherwise
        # the GCE realizer derives e2-custom from the plan, with 256 MiB alignment.
        if self.image.machine_type:
            selected = _PREDEFINED_MACHINE.fullmatch(self.image.machine_type)
            if selected is None or int(selected.group(1)) != cpu:
                raise ValueError("Worker machine type must be a predefined shape with the plan's vCPU count")
        elif cpu not in range(2, 33, 2) or ram % (256 * 1024**2) or not cpu * 512 * 1024**2 <= ram <= cpu * 8 * 1024**3:
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

    @property
    def hardware(self) -> dict[str, object]:
        """Return the provider settings that the realized host must report."""
        _, _, _, cpu, ram = worker_host_shape(self.plan)
        selected = {
            "machine_type": self.image.machine_type or f"e2-custom-{cpu}-{ram // 1024**2}",
            "enable_secure_boot": self.image.enable_secure_boot,
            "image_id": self.image_id,
        }
        # Empty interface choices keep the provider default and are not compared.
        return selected | self.image.model_dump(include={"nic_type", "disk_interface"})


ProfileName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
DEFAULT_PROFILE = "default"


class WorkerProfileError(RuntimeError):
    """The selected worker host profile is not published, or its digest changed."""


class WorkerProfileBinding(ClosedModel):
    """The exact host profile that an admitted batch retains for all of its workers."""

    name: ProfileName
    digest: Digest


class WorkerPolicy(ClosedModel):
    """Global limits and named host profiles are published by the operator, never chosen by a launch."""

    profiles: dict[ProfileName, WorkerHostProfile] = Field(min_length=1, max_length=16)
    max_live: Annotated[int, Field(strict=True, ge=1, le=1000)]
    max_provisioning: Annotated[int, Field(strict=True, ge=1, le=100)]
    lifetime_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)] = 3600
    recovery_attempts: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    hold_review_seconds: Annotated[int, Field(strict=True, ge=60, le=604800)] = 86400

    @model_validator(mode="before")
    @classmethod
    def single_profile(cls, value: object) -> object:
        """Load a policy published with one unnamed profile as the default profile."""
        if isinstance(value, dict) and "profile" in value and "profiles" not in value:
            value = {key: item for key, item in value.items() if key != "profile"} | {
                "profiles": {DEFAULT_PROFILE: value["profile"]}
            }
        return value

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        """Keep provisioning concurrency within the global live bound."""
        if self.max_provisioning > self.max_live:
            raise ValueError("Worker concurrency exceeds live capacity")
        return self

    def select(self, binding: WorkerProfileBinding | str) -> WorkerHostProfile:
        """Return the named profile; refuse a missing profile or one whose digest changed."""
        name = binding if isinstance(binding, str) else binding.name
        profile = self.profiles.get(name)
        if profile is None or (isinstance(binding, WorkerProfileBinding) and profile.digest != binding.digest):
            raise WorkerProfileError("Worker profile is unavailable or changed")
        return profile


def _validate_worker_image(image: RuntimeTargetImageProfile) -> None:
    """Accept only an exact standard GCE host without egress overrides."""
    if (
        image.provider != "gcp"
        or image.image_kind != "image"
        or image.bootstrap_capability != "standard"
        or image.disk_size_gb is None
        or not image.management_ssh_username
        or image.allow_public_web_egress
    ):
        raise ValueError("Worker host requires an exact standard GCE image profile")
