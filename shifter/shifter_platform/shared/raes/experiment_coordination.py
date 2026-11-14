"""BigRAE as the RAES coordinator of an admitted experiment batch (issue #2914).

RAES owns the trial lifecycle, the attempt and replacement decisions, and the
records. BigRAE admits the retained inputs to a RAES coordinator, assigns each
entry to the worker that it places, stages the assignment, and ingests the
outcome. The coordinator never runs a trial: its backend components refuse
every native call. This module holds no store, worker, or provider access.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal, NoReturn

from raes import canonical_sdl_bytes
from raes.scenario import ExpandedScenario
from raes_backend_protocols.manifest import backend_manifest_from_v2_model_with_envelope
from raes_contracts.canonical import canonical_json_bytes
from raes_contracts.contracts import (
    AdmittedTrialPlanModel,
    BackendManifestV2Model,
    ExperimentCaptureSpecModel,
    ExperimentSpecModel,
    ExperimentTaskModel,
    ProcessorManifestV2Model,
)
from raes_contracts.errors import ConflictError
from raes_contracts.realization_envelope import BackendRealizationEnvelopeModel
from raes_processor.trial_realization import TrialRealizationInputs
from raes_runtime import RuntimeTarget
from shifter_adapter_sdk.trial import ApparatusManifestEntry, AssignedTrialInputs

#: The RAES target name on the coordinator and on every worker that serves an assigned trial.
TRIAL_TARGET_NAME = "bigrae-worker-trial"

ApparatusKey = tuple[str, str, str, str]


def retained_family_digest(inputs: dict[str, Any]) -> str:
    """Return the canonical digest of the retained scenario family."""
    return "sha256:" + hashlib.sha256(canonical_json_bytes(inputs["family"])).hexdigest()


def _documents(inputs: dict[str, Any]) -> tuple[BackendManifestV2Model, ProcessorManifestV2Model, Any]:
    """Return the admitted backend, processor, and envelope; derived documents replace absent ones."""
    authority, derived = inputs["authority"], inputs.get("derived_apparatus") or {}
    backend = BackendManifestV2Model.model_validate(derived.get("backend") or authority["backend"])
    processor = ProcessorManifestV2Model.model_validate(authority["processor"])
    envelope = BackendRealizationEnvelopeModel.model_validate(
        derived.get("realization_envelope") or authority["realization_envelope"]
    )
    return backend, processor, envelope


def _key(kind: str, manifest: BackendManifestV2Model | ProcessorManifestV2Model) -> ApparatusKey:
    return (kind, manifest.identity.name, manifest.identity.version, manifest.schema_version)


def _entry(
    kind: Literal["backend", "processor"], manifest: BackendManifestV2Model | ProcessorManifestV2Model
) -> ApparatusManifestEntry:
    return ApparatusManifestEntry(
        kind=kind,
        name=manifest.identity.name,
        version=manifest.identity.version,
        schema_version=manifest.schema_version,
        manifest=manifest.model_dump(mode="json"),
    )


def assigned_trial_inputs(inputs: dict[str, Any]) -> AssignedTrialInputs:
    """Return the ``inputs.json`` that dispatch stages for every entry of the batch."""
    backend, processor, envelope = _documents(inputs)
    return AssignedTrialInputs(
        family_digest=retained_family_digest(inputs),
        experiment=inputs["experiment"],
        task=inputs["task"],
        capture_specs=inputs["capture_specs"],
        apparatus_manifests=[_entry("backend", backend), _entry("processor", processor)],
        realization_envelope=envelope.model_dump(mode="json"),
        backend=backend.identity.name,
    )


def realization_inputs(inputs: dict[str, Any], family: ExpandedScenario) -> TrialRealizationInputs:
    """Return the original RAES realization inputs; ``family`` comes from the registered pack."""
    if canonical_json_bytes(inputs["family"]) != canonical_sdl_bytes(family):
        raise ValueError("The registered pack family differs from the admitted family")
    backend, processor, envelope = _documents(inputs)
    return TrialRealizationInputs(
        plan=AdmittedTrialPlanModel.model_validate(inputs["plan"]),
        family=family,
        experiment=ExperimentSpecModel.model_validate(inputs["experiment"]),
        task=ExperimentTaskModel.model_validate(inputs["task"]),
        capture_specs={
            key: ExperimentCaptureSpecModel.model_validate(value) for key, value in inputs["capture_specs"].items()
        },
        apparatus_manifests={_key("backend", backend): backend, _key("processor", processor): processor},
        realization_envelope=envelope,
        backend_key=_key("backend", backend),
    )


class _RemoteOnly:
    """A backend component of the coordinator: every native call is refused."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)

        def refuse(*_args: object, **_kwargs: object) -> NoReturn:
            raise ConflictError("The RAES coordinator runs no trial; its worker does")

        return refuse


class CoordinatorTrialServices:
    """The coordinator's RAES trial services. The worker runs every trial phase.

    Admission has no effect here: the worker's own services check its installed
    settings, capture, cleanup, and stop support when it binds the assignment.
    Every other phase is refused.
    """

    def admit(self, request: object) -> None:
        return None

    def _refuse(self, *_args: object) -> NoReturn:
        raise ConflictError("The RAES coordinator runs no trial phase; its worker does")

    configure = observe = capture = cleanup = stop = verify = prepare_retry = _refuse


def coordinator_target(realization: TrialRealizationInputs) -> RuntimeTarget:
    """Return the coordinator's RAES target: the admitted backend manifest with components that refuse."""
    backend = realization.apparatus_manifests[realization.backend_key]
    if not isinstance(backend, BackendManifestV2Model):
        raise TypeError("The admitted backend key does not name a backend manifest")
    manifest = backend_manifest_from_v2_model_with_envelope(backend, realization.realization_envelope)
    refuse = _RemoteOnly()
    optional = {
        name: refuse
        for name, present in (
            ("orchestrator", manifest.orchestrator),
            ("evaluator", manifest.evaluator),
            ("participant_runtime", manifest.participant_runtime),
            ("time_runtime", manifest.time),
        )
        if present is not None
    }
    return RuntimeTarget(name=TRIAL_TARGET_NAME, manifest=manifest, provisioner=refuse, **optional)


__all__ = [
    "TRIAL_TARGET_NAME",
    "CoordinatorTrialServices",
    "assigned_trial_inputs",
    "coordinator_target",
    "realization_inputs",
    "retained_family_digest",
]
