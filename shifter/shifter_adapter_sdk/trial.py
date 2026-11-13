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

An apparatus that declares ``trial.assigned`` instead serves an RAES assigned
trial, and BigRAE is the RAES coordinator. BigRAE stages ``assigned-trial.json``,
the RAES ``assigned-trial/v1`` assignment, and ``inputs.json``, the original
trial realization inputs except the scenario family. The adapter loads the
family from its installed pack and refuses a family whose digest differs. Before
``stop``, BigRAE also stages ``control.json``, the RAES coordinator's
``assigned-trial-control/v1`` intent. The adapter binds the assignment in the
RAES runtime and advances it; the runtime, not the adapter, decides what runs.
``export`` writes one archive that holds ``outcome.json``, the RAES
``trial-outcome/v1`` at that lifecycle cut, and the evidence that it references,
sealed with ``AssignedTrialSeal``.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from .runtime import ClosedModel, decode_message

TRIAL_CONTROL_CAPABILITY: Final = "trial.control"
TRIAL_ASSIGNED_CAPABILITY: Final = "trial.assigned"
TRIAL_CONTROL_COMMAND: Final = "/usr/local/libexec/bigrae/trial-control"
TRIAL_ROOT: Final = "/var/lib/bigrae/trial"
TRIAL_INPUT_DIRECTORY: Final = TRIAL_ROOT + "/input"
TRIAL_INPUT_FILE: Final = "trial.json"
TRIAL_UNIT_FILE: Final = "trial-unit.json"
TRIAL_SCENARIO_FILE: Final = "scenario.sdl"
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
    """The staged ``trial.json``: identities, the deadline and the scenario and trial unit digests."""

    schema_version: Literal["bigrae.trial-input/v1"] = "bigrae.trial-input/v1"
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    deadline: Annotated[str, Field(max_length=40)]
    unit_sha256: Sha256
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


ASSIGNED_TRIAL_INPUT_FILE: Final = "assigned-trial.json"
TRIAL_ASSIGNMENT_FILE: Final = "assignment.json"
TRIAL_INPUTS_FILE: Final = "inputs.json"
TRIAL_CONTROL_FILE: Final = "control.json"
TRIAL_OUTCOME_FILE: Final = "outcome.json"
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
JsonObject = dict[str, object]


class AssignedTrialInput(ClosedModel):
    """The staged ``assigned-trial.json``: identities, the deadline and the staged input digests."""

    schema_version: Literal["bigrae.assigned-trial-input/v1"] = "bigrae.assigned-trial-input/v1"
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    deadline: Annotated[str, Field(max_length=40)]
    assignment_sha256: Sha256
    inputs_sha256: Sha256

    @model_validator(mode="after")
    def utc_deadline(self) -> Self:
        if not _UTC_TIME.fullmatch(self.deadline):
            raise ValueError("trial deadline must be an RFC 3339 UTC time ending in Z")
        return self


class ApparatusManifestEntry(ClosedModel):
    """One admitted apparatus manifest and the key that the trial compiler used for it."""

    kind: Literal["backend", "processor"]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    version: Annotated[str, Field(min_length=1, max_length=128)]
    schema_version: Annotated[str, Field(min_length=1, max_length=128)]
    manifest: JsonObject


class AssignedTrialInputs(ClosedModel):
    """The staged ``inputs.json``: the original realization inputs; the plan travels in the assignment."""

    schema_version: Literal["bigrae.assigned-trial-inputs/v1"] = "bigrae.assigned-trial-inputs/v1"
    family_digest: Digest
    experiment: JsonObject
    task: JsonObject
    capture_specs: dict[Annotated[str, Field(min_length=1, max_length=256)], JsonObject] = Field(max_length=64)
    apparatus_manifests: list[ApparatusManifestEntry] = Field(min_length=2, max_length=16)
    realization_envelope: JsonObject
    backend: Annotated[str, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def one_selected_backend(self) -> Self:
        if [entry.name for entry in self.apparatus_manifests if entry.kind == "backend"].count(self.backend) != 1:
            raise ValueError("the selected backend must name exactly one backend manifest")
        return self


class AssignedTrialSeal(ClosedModel):
    """``seal.json`` of an archive whose ``outcome.json`` is an RAES trial outcome.

    The inventory names every archive member except this seal. The outcome
    digest binds the exact outcome bytes; the outcome is untrusted until the
    RAES coordinator verifies and ingests it.
    """

    schema_version: Literal["bigrae.assigned-trial-seal/v1"] = "bigrae.assigned-trial-seal/v1"
    seal_state: Literal["sealed"] = "sealed"
    sealed_contract_versions: tuple[Literal["trial-outcome/v1"]] = ("trial-outcome/v1",)
    run_id: TrialIdentifier
    attempt_id: TrialIdentifier
    outcome_digest: Digest
    inventory: list[SealedMember] = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def outcome_in_inventory(self) -> Self:
        paths = [member.path for member in self.inventory]
        if len(paths) != len(set(paths)) or TRIAL_OUTCOME_FILE not in paths:
            raise ValueError("the inventory must name each member once, including the outcome")
        outcome = next(member for member in self.inventory if member.path == TRIAL_OUTCOME_FILE)
        if "sha256:" + outcome.checksum.value != self.outcome_digest:
            raise ValueError("the outcome digest differs from its inventory checksum")
        return self


def parse_trial_output[ModelT: ClosedModel](raw: bytes, model: type[ModelT]) -> ModelT:
    """Validate one bounded, unambiguous JSON object from untrusted verb output."""
    return model.model_validate(decode_message(raw.strip(), limit=MAX_TRIAL_OUTPUT_BYTES))


__all__ = [
    "ASSIGNED_TRIAL_INPUT_FILE",
    "MAX_TRIAL_ARCHIVE_BYTES",
    "MAX_TRIAL_OUTPUT_BYTES",
    "TRIAL_ASSIGNED_CAPABILITY",
    "TRIAL_ASSIGNMENT_FILE",
    "TRIAL_CONTROL_CAPABILITY",
    "TRIAL_CONTROL_FILE",
    "TRIAL_CONTROL_COMMAND",
    "TRIAL_EXPORT_DIRECTORY",
    "TRIAL_INPUT_DIRECTORY",
    "TRIAL_INPUT_FILE",
    "TRIAL_INPUTS_FILE",
    "TRIAL_OUTCOME_FILE",
    "TRIAL_ROOT",
    "TRIAL_UNIT_FILE",
    "TRIAL_SCENARIO_FILE",
    "TRIAL_SEAL_FILE",
    "TRIAL_VERBS",
    "ApparatusManifestEntry",
    "AssignedTrialInput",
    "AssignedTrialInputs",
    "AssignedTrialSeal",
    "TrialExport",
    "TrialInput",
    "TrialSeal",
    "TrialStatus",
    "TrialVerb",
    "parse_trial_output",
]
