"""Fixed worker trial-control contract between BigRAE and an apparatus adapter.

An apparatus plugin that declares ``trial.control`` installs one executable at
``TRIAL_CONTROL_COMMAND`` during its configure phase. BigRAE stages one trial's
inputs under ``TRIAL_INPUT_DIRECTORY`` and runs the executable with exactly one
verb argument. The host owns the transport, the paths, and the verbs; the
adapter owns what the verbs do. Verb output is untrusted guest data.

``start`` runs the trial in the foreground until it ends. The host detaches it.
``status`` and ``stop`` return at once. ``export`` writes one sealed archive
under ``TRIAL_EXPORT_DIRECTORY`` and reports its identity.

An apparatus that records the trial as an RAES ``experiment-run/v1`` record
seals the archive with ``TrialSeal``. The record is ``partial``: the worker
cannot know the cleanup that BigRAE performs after the trial.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from .runtime import ClosedModel, decode_message

TRIAL_CONTROL_CAPABILITY: Final = "trial.control"
TRIAL_CONTROL_COMMAND: Final = "/usr/local/libexec/bigrae/trial-control"
TRIAL_ROOT: Final = "/var/lib/bigrae/trial"
TRIAL_INPUT_DIRECTORY: Final = TRIAL_ROOT + "/input"
TRIAL_INPUT_FILE: Final = "trial.json"
TRIAL_SCENARIO_FILE: Final = "scenario.sdl"
TRIAL_PLAN_FILE: Final = "plan.json"
TRIAL_SEAL_FILE: Final = "seal.json"
TRIAL_EXPORT_DIRECTORY: Final = TRIAL_ROOT + "/export"
TRIAL_VERBS: Final = ("start", "status", "stop", "export")
MAX_TRIAL_OUTPUT_BYTES: Final = 65_536
MAX_TRIAL_ARCHIVE_BYTES: Final = 8 * 1024**3

TrialVerb = Literal["start", "status", "stop", "export"]
TrialIdentifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\w[\w.-]{0,127}$")]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
_UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class TrialInput(ClosedModel):
    """The staged ``trial.json``: identities, the deadline and the trial SDL digest."""

    schema_version: Literal["bigrae.trial-input/v1"] = "bigrae.trial-input/v1"
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    deadline: Annotated[str, Field(max_length=40)]
    scenario_sha256: Sha256

    @model_validator(mode="after")
    def utc_deadline(self) -> Self:
        if not _UTC_TIME.fullmatch(self.deadline):
            raise ValueError("trial deadline must be an RFC 3339 UTC time ending in Z")
        return self


class TrialStatus(ClosedModel):
    """``status`` output. ``sealed`` reports the adapter's claim only."""

    schema_version: Literal["bigrae.trial-status/v1"] = "bigrae.trial-status/v1"
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    state: Literal["prepared", "running", "exited"]
    sealed: bool
    exit_code: Annotated[int, Field(strict=True, ge=0, le=255)] | None = None

    @model_validator(mode="after")
    def exit_code_after_exit(self) -> Self:
        if (self.state == "exited") != (self.exit_code is not None):
            raise ValueError("only an exited trial reports an exit code")
        if self.sealed and self.state != "exited":
            raise ValueError("only an exited trial can be sealed")
        return self


class TrialExport(ClosedModel):
    """``export`` output: one archive file under the export directory."""

    schema_version: Literal["bigrae.trial-export/v1"] = "bigrae.trial-export/v1"
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    file: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    sha256: Sha256
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_TRIAL_ARCHIVE_BYTES)]


class SealedChecksum(ClosedModel):
    algorithm: Literal["sha256"] = "sha256"
    value: Sha256


class SealedMember(ClosedModel):
    """One archive member and its exact bytes."""

    path: Annotated[str, Field(min_length=1, max_length=512)]
    size_bytes: Annotated[int, Field(strict=True, ge=0)]
    checksum: SealedChecksum
    media_type: Annotated[str, Field(min_length=1, max_length=128)]
    role: Annotated[str, Field(min_length=1, max_length=128)]


class SealedCompleteness(ClosedModel):
    complete: bool
    limitations: list[Annotated[str, Field(min_length=1, max_length=1024)]]

    @model_validator(mode="after")
    def complete_without_limitations(self) -> Self:
        if self.complete == bool(self.limitations):
            raise ValueError("a complete archive has no limitations")
        return self


class TrialSeal(ClosedModel):
    """``seal.json`` of an archive whose ``manifest.json`` is an RAES experiment-run record.

    The inventory names every archive member except this seal and the optional
    ``checksums.sha256``. The run fields repeat the record so that intake can
    refuse a seal that contradicts it.
    """

    schema_version: Literal["bigrae.trial-seal/v1"] = "bigrae.trial-seal/v1"
    seal_state: Literal["sealed"] = "sealed"
    sealed_contract_versions: tuple[Literal["experiment-run/v1"]] = ("experiment-run/v1",)
    run_id: TrialIdentifier
    run_version: TrialIdentifier
    run_status: Annotated[str, Field(min_length=1, max_length=32)]
    outcome_status: Annotated[str, Field(min_length=1, max_length=32)]
    run_record_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    completeness: SealedCompleteness
    inventory: list[SealedMember] = Field(min_length=1, max_length=20_000)


def parse_trial_output[ModelT: ClosedModel](raw: bytes, model: type[ModelT]) -> ModelT:
    """Validate one bounded, unambiguous JSON object from untrusted verb output."""
    return model.model_validate(decode_message(raw.strip(), limit=MAX_TRIAL_OUTPUT_BYTES))


__all__ = [
    "MAX_TRIAL_ARCHIVE_BYTES",
    "MAX_TRIAL_OUTPUT_BYTES",
    "TRIAL_CONTROL_CAPABILITY",
    "TRIAL_CONTROL_COMMAND",
    "TRIAL_EXPORT_DIRECTORY",
    "TRIAL_INPUT_DIRECTORY",
    "TRIAL_INPUT_FILE",
    "TRIAL_PLAN_FILE",
    "TRIAL_ROOT",
    "TRIAL_SCENARIO_FILE",
    "TRIAL_SEAL_FILE",
    "TRIAL_VERBS",
    "TrialExport",
    "TrialInput",
    "TrialSeal",
    "TrialStatus",
    "TrialVerb",
    "parse_trial_output",
]
