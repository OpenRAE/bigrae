"""Closed input and receipt for the native ``worker-trial`` operations.

Engine writes the input; the provisioner reads it. The provisioner writes the
receipt; Engine applies it. No field carries a credential, a bucket name, or
scientific content. Staged files live in the provisioner's configured object
storage under fixed prefixes; their digests bind them to this operation.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TRIAL_INPUT_PREFIX = "trial-inputs/"
TRIAL_EXPORT_PREFIX = "trial-exports/"
STAGED_FILES = ("trial.json", "scenario.sdl", "pack.tar")
MAX_STAGED_BYTES = 1024**3
MAX_ARCHIVE_BYTES = 8 * 1024**3

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ObjectKey = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9/._-]*$")]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StagedObject(_Closed):
    key: ObjectKey
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=1, le=MAX_STAGED_BYTES)]

    @model_validator(mode="after")
    def staged_prefix(self) -> Self:
        if not self.key.startswith(TRIAL_INPUT_PREFIX) or ".." in self.key:
            raise ValueError("staged trial object is outside its prefix")
        return self


class WorkerTrialInput(_Closed):
    """One trial's native operation input."""

    trial_id: UUID
    generation: UUID
    range_request_id: UUID
    provision_operation_id: UUID
    deadline: Annotated[str, Field(min_length=20, max_length=40)]
    staged: dict[str, StagedObject]
    stop: bool = False

    @model_validator(mode="after")
    def complete_staging(self) -> Self:
        if set(self.staged) != set(STAGED_FILES):
            raise ValueError("worker trial staging is incomplete")
        return self


class ArchiveObject(_Closed):
    key: ObjectKey
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=1, le=MAX_ARCHIVE_BYTES)]

    @model_validator(mode="after")
    def export_prefix(self) -> Self:
        if not self.key.startswith(TRIAL_EXPORT_PREFIX) or ".." in self.key:
            raise ValueError("trial archive is outside its prefix")
        return self


class WorkerTrialReceipt(_Closed):
    """The observed trial state; ``archive`` is set only for a sealed export."""

    trial_id: UUID
    state: Literal["prepared", "running", "exited"]
    exit_code: Annotated[int, Field(ge=0, le=255)] | None = None
    sealed: bool = False
    archive: ArchiveObject | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.state == "exited") != (self.exit_code is not None):
            raise ValueError("only an exited trial reports an exit code")
        if self.archive is not None and not self.sealed:
            raise ValueError("only a sealed trial has an archive")
        return self


def parse_worker_trial_input(payload: object) -> WorkerTrialInput:
    return WorkerTrialInput.model_validate(payload)


def parse_worker_trial_receipt(payload: object) -> WorkerTrialReceipt:
    return WorkerTrialReceipt.model_validate(payload)
