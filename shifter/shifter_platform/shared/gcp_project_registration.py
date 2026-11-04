"""Reference-only native registration transport for an existing GCP project."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator
from shifter_adapter_sdk.runtime import ClosedModel

from shared.gcp_range_projects import GcpBaselineRef, ProjectID, ProjectNumber

BucketName = Annotated[str, Field(strict=True, min_length=3, max_length=222, pattern=r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$")]
PROTECTED_PROJECT_ENV_NAMES = (
    "GCP_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUD_PROJECT_ID",
    "GCP_RANGE_CELL_PROJECT_ID",
    "GCP_DYNAMIC_SECRET_PROJECT_ID",
    "IDENTITY_PLATFORM_PROJECT_ID",
)

PROTECTED_IMAGE_ENV_NAMES = (
    "GCP_RANGE_LINUX_IMAGE",
    "GCP_RANGE_KALI_IMAGE",
    "GCP_RANGE_WINDOWS_IMAGE",
    "GCP_RANGE_DC_IMAGE",
)


def configured_project_ids(projects: Iterable[str], image_refs: Iterable[str]) -> list[str]:
    """Extract only provider project custody from administrator-owned root configuration."""
    identifiers = set(filter(None, projects))
    for reference in image_refs:
        path = reference.removeprefix("https://www.googleapis.com/compute/v1/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "projects":
            identifiers.add(parts[1])
    return sorted(TypeAdapter(ProjectID).validate_python(identifier) for identifier in identifiers)


class GcpProjectRegistrationInput(ClosedModel):
    """Server-owned input; an API caller cannot choose artifact storage or exclusions."""

    schema_version: Literal["bigrae.gcp-project-registration/v1"] = "bigrae.gcp-project-registration/v1"
    registration_id: UUID
    organization_uuid: UUID
    project_id: ProjectID
    bucket: BucketName
    protected_project_ids: list[ProjectID] = Field(min_length=1, max_length=64)
    baseline: GcpBaselineRef | None = None

    @model_validator(mode="after")
    def require_dedicated_project(self) -> GcpProjectRegistrationInput:
        """Shared deployment infrastructure cannot become a mutable scenario project."""
        if self.project_id in self.protected_project_ids or len(set(self.protected_project_ids)) != len(
            self.protected_project_ids
        ):
            raise ValueError("Registered project is unavailable")
        if self.baseline is not None and (
            self.baseline.registration_id != self.registration_id or self.baseline.bucket != self.bucket
        ):
            raise ValueError("Registered project is unavailable")
        return self


class GcpProjectRegistrationReceipt(ClosedModel):
    """No raw provider inventory crosses the operation-result budget."""

    registration_id: UUID
    organization_uuid: UUID
    project_id: ProjectID
    project_number: ProjectNumber
    baseline: GcpBaselineRef

    def authorize(self, original: GcpProjectRegistrationInput, operation_id: UUID) -> None:
        """Bind accepted capture to its original scope, generation and storage root."""
        if (
            self.registration_id,
            self.organization_uuid,
            self.project_id,
            self.baseline.registration_id,
            self.baseline.capture_operation_id,
            self.baseline.bucket,
        ) != (
            original.registration_id,
            original.organization_uuid,
            original.project_id,
            original.registration_id,
            original.baseline.capture_operation_id if original.baseline is not None else operation_id,
            original.bucket,
        ):
            raise ValueError("Registered project capture is unavailable")
        if original.baseline is not None and self.baseline != original.baseline:
            raise ValueError("Registered project capture is unavailable")
