"""Pure released pack/RAES admission; no worker, provider or model execution."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from raes import admit_scenario_family, canonical_sdl_bytes, canonical_sdl_digest, parse_sdl
from raes.canonical import canonical_instantiated_sdl_bytes
from raes.participant_control_context import SDLControlContextConfigurationValidator, authored_control_context_bindings
from raes.scenario import InstantiatedScenario
from raes_contracts.associated_artifacts import AssociatedArtifactValidationLimits
from raes_contracts.canonical import canonical_json_bytes, canonical_json_digest
from raes_contracts.contracts import (
    AdmittedApparatusBindingModel,
    AdmittedParticipantManifestReferenceModel,
    AdmittedTrialEntryModel,
    BackendManifestV2Model,
    ExperimentArtifactRefModel,
    ExperimentManifestReferenceModel,
    ParticipantImplementationManifestModel,
    ProcessorManifestV2Model,
    TrialCleanupReceiptModel,
    TrialCompilationLimitsModel,
    TrialExecutionAuthorityModel,
    validate_trial_cleanup_receipt,
)
from raes_contracts.contracts.admitted_trial_plan_ingress import parse_admitted_trial_plan_json
from raes_contracts.errors import RaesError
from raes_contracts.json_ingress import StrictJsonIngressError, parse_bounded_json, parse_bounded_json_object
from raes_contracts.participant_control_context import control_context_asset_reference
from raes_contracts.realization_envelope import BackendRealizationEnvelopeModel
from raes_env_packs import PackExperiment, load_pack_experiments, resolve_pack_artifact, validate_pack_content_manifest
from raes_processor.trial_compiler import compile_admitted_trial_plan
from raes_processor.trial_realization import instantiate_admitted_trial_entry
from raes_processor.trial_scheduler import BatchSchedule, plan_batch_schedule

from shared.raes.pack_delivery_inputs import pack_artifact_relative_path
from shared.raes.participant_owner_replay import (
    OwnerValidation,
    ReplayedConfigurationValidator,
)
from shared.raes.participant_owner_replay import validation_requests as _validation_requests
from shared.raes.trial_archive import TrialArchiveIdentity, safe_archive_path
from shared.raes.trial_archive_records import reject_retained_credentials

ExperimentInputError = RaesError

MAX_RETAINED_BYTES = 64 * 1024**2
MAX_AUTHORITY_BYTES = 4 * 1024**2
MAX_DOCUMENT_BYTES = 16 * 1024**2
SUPPORTED_DEPENDENCIES = {"raes": "11.0.1", "raes-env-packs": "7.2.3"}


class ParticipantAuthority(BaseModel):
    """An administrator's explicit participant-to-owner-manifest binding."""

    model_config = ConfigDict(extra="forbid", strict=True)
    participant_address: str = Field(min_length=1, max_length=128)
    manifest: ParticipantImplementationManifestModel


class ExperimentAuthority(BaseModel):
    """Native admission configuration, composing unmodified owner contracts.

    Only installation content administrators may submit this configuration.
    It is neither a portable scientific schema nor an execution permission.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["bigrae.experiment-admission-authority/v1"]
    backend: BackendManifestV2Model
    processor: ProcessorManifestV2Model
    participants: list[ParticipantAuthority] = Field(default_factory=list, max_length=256)
    realization_envelope: BackendRealizationEnvelopeModel
    execution_authority: TrialExecutionAuthorityModel
    max_concurrency: int = Field(default=200, ge=1, le=10000)


def dependency_tuple() -> dict[str, str]:
    """Fail closed outside the reviewed installed scientific dependency tuple."""
    installed = {name: version(name) for name in SUPPORTED_DEPENDENCIES}
    if (
        installed != SUPPORTED_DEPENDENCIES
        or sys.version_info[:2] != (3, 14)
        or not version("django").startswith("6.0.")
    ):
        raise ValueError("Unsupported experiment dependency tuple")
    return {**installed, "python": f"{sys.version_info.major}.{sys.version_info.minor}", "django": version("django")}


def encode_retained(payload: object) -> str:
    """Use the released canonicalizer for bounded retained record bytes."""
    raw = canonical_json_bytes(payload)
    if len(raw) > MAX_RETAINED_BYTES:
        raise ValueError("Experiment retained inputs exceed the byte limit")
    return raw.decode("utf-8")


def validate_retained(raw: str) -> dict[str, Any]:
    """Validate retained plan ingress without compilation, sampling or allocation."""
    payload = cast(dict[str, Any], parse_bounded_json_object(raw, max_bytes=MAX_RETAINED_BYTES, max_depth=128))
    installed = dependency_tuple()
    if (
        any(payload["dependencies"].get(name) != installed[name] for name in SUPPORTED_DEPENDENCIES)
        or payload["dependencies"].get("python") != "3.14"
        or not str(payload["dependencies"].get("django", "")).startswith("6.0.")
    ):
        raise ValueError("Unsupported experiment dependency tuple")
    plan = parse_admitted_trial_plan_json(canonical_json_bytes(payload["plan"]))
    schedule = plan_batch_schedule(plan)
    if set(payload.get("snapshot_digests", payload.get("snapshots", {}))) != set(plan.entries):
        raise ValueError("Retained snapshot set differs from plan entries")
    limits = payload["resource_limits"]
    _concurrency(limits["requested_concurrency"], limits["configured_concurrency_ceiling"], schedule)
    if limits["isolation_ceiling"] != schedule.admitted_parallelism_ceiling:
        raise ValueError("Retained isolation ceiling differs from plan")
    return payload


def _concurrency(requested: int, configured: int, schedule: BatchSchedule) -> None:
    """Keep requested concurrency inside the administrative limit and the admitted plan bounds."""
    floor, ceiling = schedule.admitted_parallelism_floor, schedule.admitted_parallelism_ceiling
    if type(requested) is not int or not floor <= requested <= min(configured, ceiling):
        raise ValueError("Requested concurrency is outside the configured or admitted limits")


def _context(
    experiment: PackExperiment, authority: ExperimentAuthority, owner_validation: OwnerValidation | None = None
) -> dict[str, Any]:
    """Compose explicit owner manifests into the released compiler context."""
    owned: dict[tuple[str, str], list[dict[str, Any]]] = {}
    manifests = {}
    references = []
    for kind, manifest in (("backend", authority.backend), ("processor", authority.processor)):
        key = (kind, manifest.identity.name, manifest.identity.version, manifest.schema_version)
        manifests[key] = manifest
        references.append(
            ExperimentManifestReferenceModel.model_validate(
                {
                    "ref_kind": "manifest",
                    "ref_id": manifest.identity.name,
                    "ref_version": manifest.schema_version,
                    "ref_digest": canonical_json_digest(manifest.model_dump(mode="json")),
                    "subject_ref": {
                        "ref_kind": kind,
                        "ref_id": manifest.identity.name,
                        "ref_version": manifest.identity.version,
                    },
                }
            )
        )
    participants: dict[tuple[str, str, str, str], ParticipantImplementationManifestModel] = {}
    participant_refs = []
    validators = {}
    for binding in authority.participants:
        manifest = binding.manifest
        key = (binding.participant_address, manifest.identity.name, manifest.identity.version, manifest.schema_version)
        if key in participants or any(k[0] == key[0] for k in participants):
            raise ValueError("Duplicate participant authority")
        participants[key] = manifest
        participant_refs.append(
            AdmittedParticipantManifestReferenceModel(
                participant_address=key[0],
                implementation_name=key[1],
                implementation_version=key[2],
                manifest_version=key[3],
                manifest_digest=canonical_json_digest(manifest.model_dump(mode="json")),
            )
        )
        registry = manifest.configuration_registry
        if registry is not None:
            owner = (registry.owner.validator_id, registry.owner.validator_version)
            # The published SDL owner adapter runs here; any other owner runs in its
            # installed adapter (``validate`` phase) and is replayed, never imported.
            if owner == ("participant-config", "1"):
                validators[owner] = SDLControlContextConfigurationValidator(experiment.family)
            elif owner_validation is None:
                raise ValueError("Unsupported participant configuration owner")
            else:
                owned.setdefault(owner, []).extend(
                    _validation_requests(experiment, binding.participant_address, manifest)
                )
    if owner_validation is not None:
        family_digest = canonical_sdl_digest(experiment.family).value
        for owner, requests in owned.items():
            results = owner_validation(f"{owner[0]}@{owner[1]}", family_digest, requests)
            validators[owner] = ReplayedConfigurationValidator.from_results(requests, results)
    apparatus = AdmittedApparatusBindingModel(
        manifest_refs=references,
        participant_manifest_refs=participant_refs,
        realization_envelope=authority.realization_envelope.identity,
        capability_refs=sorted(experiment.experiment.apparatus_intent.required_capabilities),
    )
    return {
        "apparatus": apparatus,
        "apparatus_manifests": manifests,
        "participant_manifests": participants,
        "participant_configuration_validators": validators,
        "realization_envelope": authority.realization_envelope,
        "execution_authority": authority.execution_authority,
        "limits": TrialCompilationLimitsModel(),
    }


def _documents(root: Path, experiment: PackExperiment) -> dict[str, str]:
    """Keep selected original documents under a separate aggregate input bound."""
    selected = {experiment.path, experiment.family_path}
    captures = {(item.capture_spec_id, item.spec_version) for item in experiment.capture_specs.values()}
    paths = [root / rel for rel in sorted(selected)]
    for path in sorted((root / "experiments").iterdir()):
        if not path.is_file() or not path.name.endswith((".task.json", ".capture.json")):
            continue
        with path.open("rb") as source:
            raw = source.read(1024**2 + 1)
        document = parse_bounded_json_object(raw, max_bytes=1024**2, max_depth=64)
        task_key = (document.get("task_id"), document.get("task_version"))
        capture_key = (document.get("capture_spec_id"), document.get("spec_version"))
        if task_key == (experiment.task.task_id, experiment.task.task_version) or capture_key in captures:
            paths.append(path)
    documents = {}
    remaining = MAX_DOCUMENT_BYTES
    for path in paths:
        with path.open("rb") as source:
            raw = source.read(remaining + 1)
        remaining -= len(raw)
        if remaining < 0:
            raise ValueError("Experiment original documents exceed the byte limit")
        documents[path.relative_to(root).as_posix()] = raw.decode("utf-8")
    return documents


def _check_artifact_credentials(data: bytes, media_type: str) -> None:
    """Apply existing credential rules to original bytes without altering their content."""
    media_type = media_type.partition(";")[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            parsed = parse_bounded_json(data, max_bytes=MAX_DOCUMENT_BYTES, root="object", max_depth=64)
        except StrictJsonIngressError as error:
            if error.code != "invalid-root":
                raise
            parsed = parse_bounded_json(data, max_bytes=MAX_DOCUMENT_BYTES, root="array", max_depth=64)
        reject_retained_credentials(parsed)
    else:
        reject_retained_credentials(data.decode("utf-8", errors="replace"))


class _ArtifactCustody:
    """Cache exact inventory-bound input bytes under one aggregate retention budget."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.inventory = validate_pack_content_manifest(root)
        self.by_path = {pack_artifact_relative_path(item.uri): key for key, item in self.inventory.artifacts.items()}
        self.payload: dict[str, dict[str, Any]] = {}
        self.total = 0

    def _reference(self, reference: ExperimentArtifactRefModel, exact_descriptor: bool) -> tuple[str, str]:
        """Resolve an installed inventory identity while preserving exact selected pins."""
        is_pack_uri = urlsplit(reference.uri).scheme == "raes-environment-pack"
        if exact_descriptor and not is_pack_uri:
            raise ValueError("Selected control-context content has no supported installed byte binding")
        relative = pack_artifact_relative_path(reference.uri) if is_pack_uri else safe_archive_path(reference.uri)
        artifact_id = reference.artifact_id if exact_descriptor else self.by_path.get(relative)
        if artifact_id is None or (exact_descriptor and self.inventory.artifacts.get(artifact_id) != reference):
            raise ValueError("Referenced experiment artifact is not exactly installed")
        return relative, artifact_id

    def _retain_bytes(self, relative: str, reference: ExperimentArtifactRefModel | str, media_type: str) -> int:
        """Verify and cache original bytes once, enforcing the aggregate byte limit."""
        if relative in self.payload:
            return 0
        resolved = resolve_pack_artifact(
            self.root,
            reference,
            artifact_limits=AssociatedArtifactValidationLimits(max_artifact_bytes=MAX_DOCUMENT_BYTES - self.total),
        )
        data = resolved.data
        self.total += len(data)
        _check_artifact_credentials(data, media_type)
        retained = {
            "base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        self.payload[relative] = retained
        return len(canonical_json_bytes(retained)) + len(canonical_json_bytes(relative)) + 8

    def retain(self, references: list[ExperimentArtifactRefModel], *, exact_descriptor: bool = False) -> int:
        """Retain actual bytes once; repeated references must agree with their owner pins."""
        added = 0
        for reference in references:
            relative, artifact_id = self._reference(reference, exact_descriptor)
            added += self._retain_bytes(relative, reference if exact_descriptor else artifact_id, reference.media_type)
            retained = self.payload[relative]
            if (
                reference.checksum.algorithm != "sha256"
                or retained["sha256"] != reference.checksum.value
                or (reference.size_bytes is not None and reference.size_bytes != retained["size_bytes"])
            ):
                raise ValueError("Referenced experiment artifact bytes differ from admission")
        return added


def _selected_control_context_artifacts(
    selected: InstantiatedScenario, entry: AdmittedTrialEntryModel
) -> list[ExperimentArtifactRefModel]:
    """Join released selected asset pins to their owner descriptors without selecting treatments."""
    assets = {}
    for asset in selected.control_context_assets.values():
        pin = control_context_asset_reference(asset)
        assets[(pin.asset_id, pin.asset_version, pin.asset_digest)] = asset
    pins = [
        value.control_context_selection.asset_ref
        for configuration in entry.participant_configurations
        for value in configuration.configuration.values
        if value.control_context_selection is not None
    ]
    pins.extend(
        binding.asset_ref
        for _, _, _, binding in authored_control_context_bindings(selected)
        if binding.disposition == "selected"
    )
    references = []
    for pin in pins:
        asset = assets.get((pin.asset_id, pin.asset_version, pin.asset_digest))
        if asset is None:
            raise ValueError("Selected control-context content does not resolve to its retained owner pin")
        references.append(asset.content)
    return references


def validate_experiment_cleanup(inputs: dict[str, Any], entry_id: str, attempt_id: str, receipt: object) -> str:
    """Validate a trusted owner's cleanup report against the retained trial authority."""
    try:
        parsed = parse_bounded_json_object(canonical_json_bytes(receipt), max_bytes=MAX_AUTHORITY_BYTES, max_depth=64)
        reject_retained_credentials(parsed)
        plan = parse_admitted_trial_plan_json(canonical_json_bytes(inputs["plan"]))
        entry = plan.entries[entry_id]
        cleanup = plan.cleanup_plans[entry.execution_controls.cleanup_plan_ref]
        result = TrialCleanupReceiptModel.model_validate(parsed)
        validate_trial_cleanup_receipt(cleanup, result)
        if result.execution_attempt_id != attempt_id or result.cleanup_status != "succeeded":
            raise ValueError("Cleanup is not verified for this attempt")
        return canonical_json_bytes(result.model_dump(mode="json")).decode()
    except (ValueError, KeyError, TypeError, RaesError):
        raise ValueError("Experiment cleanup receipt is invalid or unverified") from None


def experiment_archive_identity(
    inputs: dict[str, Any],
    entry_id: str,
    attempt_id: str,
    run_version: str = "1",
    *,
    scenario_sha256: str = "",
) -> TrialArchiveIdentity:
    """Use the incumbent custody identity contract at both admission and collection."""
    plan = inputs["plan"]
    entry = plan["entries"][entry_id]
    reference = plan["input_refs"].get("study_ref") or plan["input_refs"]["authoring_input_ref"]
    return TrialArchiveIdentity(
        experiment_id=reference["ref_id"],
        plan_id=plan["plan_id"],
        entry_id=entry_id,
        run_id=entry["run_id"],
        attempt_id=attempt_id,
        plan_digest=plan["plan_digest"],
        entry_digest=entry["entry_digest"],
        run_version=run_version,
        scenario_sha256=scenario_sha256,
    )


def _select_experiment(root: Path, experiment_id: str, experiment_version: str | None) -> PackExperiment:
    """Select exactly one released pack experiment without rewriting authoring inputs."""
    candidates = [
        item
        for item in load_pack_experiments(root)
        if item.experiment.spec_id == experiment_id
        and (experiment_version is None or item.experiment.spec_version == experiment_version)
    ]
    if len(candidates) != 1:
        raise ValueError("Experiment selection is absent or ambiguous")
    return candidates[0]


def compile_pack_experiment(
    root: Path,
    *,
    experiment_id: str,
    authority: object,
    concurrency: int,
    experiment_version: str | None = None,
    owner_validation: OwnerValidation | None = None,
) -> dict[str, Any]:
    """Compile one explicitly selected installed experiment and retain its inputs."""
    dependencies = dependency_tuple()
    encoded_authority = canonical_json_bytes(authority)
    parsed = parse_bounded_json_object(encoded_authority, max_bytes=MAX_AUTHORITY_BYTES, max_depth=64)
    reject_retained_credentials(parsed)
    configuration = ExperimentAuthority.model_validate(parsed)
    if type(concurrency) is not int or not 1 <= concurrency <= configuration.max_concurrency:
        raise ValueError("Requested concurrency exceeds configured limit")
    experiment = _select_experiment(root, experiment_id, experiment_version)
    request = experiment.compilation_request(**_context(experiment, configuration, owner_validation))
    result = compile_admitted_trial_plan(request)
    if result.plan is None:
        raise ValueError("Experiment compilation refused the supplied combination")
    plan = result.plan
    schedule = plan_batch_schedule(plan)
    _concurrency(concurrency, configuration.max_concurrency, schedule)
    # The private staged tree is bounded and unchanged during this operation.
    custody = _ArtifactCustody(root)
    references = list(experiment.experiment.artifact_refs) + list(experiment.task.artifact_refs)
    for capture in experiment.capture_specs.values():
        references.extend(capture.artifact_refs)
    custody.retain(references)
    payload: dict[str, Any] = {
        "dependencies": dependencies,
        "documents": _documents(root, experiment),
        "artifacts": custody.payload,
        "family": json.loads(canonical_sdl_bytes(experiment.family)),
        "family_path": experiment.family_path,
        "experiment": experiment.experiment.model_dump(mode="json"),
        "task": experiment.task.model_dump(mode="json"),
        "capture_specs": {key: item.model_dump(mode="json") for key, item in experiment.capture_specs.items()},
        "authority": parsed,
        "plan": plan.model_dump(mode="json"),
        "snapshot_digests": {},
        "resource_limits": {
            "requested_concurrency": concurrency,
            "configured_concurrency_ceiling": configuration.max_concurrency,
            "isolation_ceiling": schedule.admitted_parallelism_ceiling,
            "compilation": request.limits.model_dump(mode="json"),
            "max_retained_bytes": MAX_RETAINED_BYTES,
            "max_original_document_bytes": MAX_DOCUMENT_BYTES,
            "max_referenced_artifact_bytes": MAX_DOCUMENT_BYTES,
            "max_authority_bytes": MAX_AUTHORITY_BYTES,
        },
    }
    retained_bytes = len(encode_retained(payload).encode())
    for entry in schedule.entries:
        experiment_archive_identity(payload, entry.plan_entry_id, "admission-validation")
        selected = instantiate_admitted_trial_entry(
            plan=plan, plan_entry_id=entry.plan_entry_id, family=experiment.family
        )
        retained_bytes += custody.retain(
            _selected_control_context_artifacts(selected, plan.entries[entry.plan_entry_id]),
            exact_descriptor=True,
        )
        snapshot = canonical_instantiated_sdl_bytes(selected)
        reject_retained_credentials(json.loads(snapshot))
        digest = "sha256:" + hashlib.sha256(snapshot).hexdigest()
        retained_bytes += len(digest) + len(entry.plan_entry_id.encode()) + 8
        if retained_bytes > MAX_RETAINED_BYTES:
            raise ValueError("Experiment hydrated inputs exceed the byte limit")
        payload["snapshot_digests"][entry.plan_entry_id] = digest
    reject_retained_credentials(payload)
    return payload


def retained_entry_snapshot(inputs: dict[str, Any], entry_id: str) -> bytes:
    """Instantiate one entry from the retained plan and family SDL and verify the admitted digest.

    A batch admitted before digests were retained keeps its snapshots in the record.
    """
    if "snapshot_digests" not in inputs:
        return canonical_json_bytes(inputs["snapshots"][entry_id])
    plan = parse_admitted_trial_plan_json(canonical_json_bytes(inputs["plan"]))
    family = admit_scenario_family(parse_sdl(inputs["documents"][inputs["family_path"]]))
    snapshot = canonical_instantiated_sdl_bytes(
        instantiate_admitted_trial_entry(plan=plan, plan_entry_id=entry_id, family=family)
    )
    if "sha256:" + hashlib.sha256(snapshot).hexdigest() != inputs["snapshot_digests"][entry_id]:
        raise ValueError("Instantiated trial snapshot differs from its admitted digest")
    return snapshot
