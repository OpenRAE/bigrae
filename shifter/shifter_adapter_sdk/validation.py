"""The ``validate`` phase: an installed adapter validates participant configurations.

A participant implementation's configuration owner belongs to the backend, not
to BigRAE. At admission, BigRAE sends the experiment's participant configurations
to the installed adapter that declares that owner, with the digest of the
admitted scenario family. The adapter's own copy of that family must match it.
The adapter runs the owner in the isolated plugin worker and returns, for each configuration, the owner's
normalized configuration and the control-context selections it accepted.
BigRAE then admits exactly those results and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from .runtime import ClosedModel, PluginManifest, canonical_digest

VALIDATE_CAPABILITY = "participant.validate"
MAX_VALIDATION_REQUESTS = 64
OwnerId = Annotated[str, Field(min_length=3, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*@[A-Za-z0-9._-]+$")]
JsonObject = dict[str, Any]


class ParticipantValidationRequest(ClosedModel):
    """One participant's manifest and its configuration overrides."""

    participant_address: Annotated[str, Field(min_length=1, max_length=256)]
    participant_manifest: JsonObject
    overrides: list[JsonObject] = Field(max_length=256)


class ParticipantValidation(ClosedModel):
    """The owner's outcome for one request."""

    input_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    normalized: JsonObject
    contexts: list[JsonObject] = Field(default_factory=list, max_length=64)


class ValidationInput(ClosedModel):
    """Configurations for one owner; no range, guest, credential or operation context."""

    protocol: Literal["bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    phase: Literal["validate"]
    manifest: PluginManifest
    owner: OwnerId
    family_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    requests: list[ParticipantValidationRequest] = Field(min_length=1, max_length=MAX_VALIDATION_REQUESTS)

    @model_validator(mode="after")
    def declared_owner(self) -> Self:
        if self.protocol != self.manifest.protocol or self.owner not in self.manifest.participant_validators:
            raise ValueError("the plugin manifest does not declare this configuration owner")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class ValidationResult(ClosedModel):
    """One outcome per request, in request order, or a bounded failure."""

    protocol: Literal["bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    phase: Literal["validate"]
    input_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    status: Literal["validated", "failed"]
    results: list[ParticipantValidation] = Field(default_factory=list, max_length=MAX_VALIDATION_REQUESTS)

    def authorize(self, request: ValidationInput) -> None:
        if (
            self.protocol != request.protocol
            or self.invocation_id != request.invocation_id
            or self.input_digest != request.digest
            or (self.status == "validated") != (len(self.results) == len(request.requests))
        ):
            raise ValueError("plugin validation does not match its invocation")


class ValidatingPlugin(Protocol):
    """Author implementation of the ``participant.validate`` capability."""

    def validate(self, request: ValidationInput) -> list[ParticipantValidation]: ...


__all__ = [
    "MAX_VALIDATION_REQUESTS",
    "VALIDATE_CAPABILITY",
    "ParticipantValidation",
    "ParticipantValidationRequest",
    "ValidatingPlugin",
    "ValidationInput",
    "ValidationResult",
]
