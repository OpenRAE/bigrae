"""Assemble a fixed native target for qualification, without generic claims.

This candidate is not installation activation or a conformance verdict. The
owning service supplies current native input and later retains proof for the
exact admitted configuration. Scenario selections can name only compiled
logical references, never executable implementation or provider configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from raes_backend_protocols.capabilities import (
    PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS,
    ParticipantFeatureSupport,
    ParticipantRuntimeCapabilities,
)
from raes_backend_protocols.participant_runtime_base import BaseParticipantRuntime
from raes_contracts.canonical import canonical_json_digest
from raes_contracts.contracts.participant_manifests import (
    ParticipantImplementationManifestModel,
    ParticipantImplementationSelectionModel,
)
from raes_contracts.diagnostics import Diagnostic
from raes_contracts.participant_native_execution import ParticipantNativeActionExecution
from raes_contracts.runtime_state import ApplyResult
from raes_contracts.vocabulary import ParticipantFeatureSupportLevel

from shared.native_participant import (
    NATIVE_POWER_CONTROL_PROFILE_REF,
    NativePowerControlSelection,
    NativeRuntimeCoordinates,
)
from shared.raes.compiled_participants import CompiledParticipantContext, restore_compiled_model
from shared.raes.native_participant_actions import (
    NativePowerActionBinding,
    NativePowerActionMapping,
    NativePowerParticipantRuntime,
    NativePowerReservationPort,
    _validate_binding,
)
from shared.raes.power_input import NativePowerInput
from shared.raes.runtime_target import create_shifter_backend_target

if TYPE_CHECKING:
    from raes.scenarios import Scenario
    from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
    from raes_contracts.runtime_state import RuntimeSnapshot
    from raes_processor.models import RuntimeModel
    from raes_runtime.registry import RuntimeTarget

    from shared.raes.dispatch_port import ShifterProvisioningDispatchPort

_FEATURES = frozenset({"participant_ingress_admission", "participant_intervention"})
_CANDIDATE_EVIDENCE = "shifter-native-power-supervision-candidate/v1"


@dataclass(frozen=True, slots=True)
class NativePowerControlCandidate:
    """Private qualification assembly; it grants no native execution permission."""

    target: RuntimeTarget = field(repr=False)
    model: RuntimeModel = field(repr=False)
    bindings: tuple[NativePowerActionBinding, ...] = field(repr=False)


class _PlanningRuntime(BaseParticipantRuntime):
    """Prospective declared support cannot become a reference no-op execution."""

    @staticmethod
    def _model_action(
        request: ParticipantActionAdmissionRequest, snapshot: RuntimeSnapshot, *, episode_id: str
    ) -> ParticipantNativeActionExecution:
        del episode_id
        return ParticipantNativeActionExecution(
            apply_result=ApplyResult(
                success=False,
                snapshot=snapshot,
                diagnostics=[
                    Diagnostic(
                        code="shifter.native-planning-only.withheld",
                        domain="runtime",
                        address=request.participant_address,
                        message="A planning target cannot execute participant actions.",
                    )
                ],
            )
        )


def _implementation_manifest() -> ParticipantImplementationManifestModel:
    return ParticipantImplementationManifestModel.model_validate(
        {
            "schema_version": "participant-implementation-manifest/v1",
            "identity": {"name": "shifter-native-power-supervision", "version": "1.0.0"},
            "implementation_kind": "human-control-proxy",
            "supported_contract_versions": [
                "participant-implementation-manifest-v1",
                "participant-episode-state-envelope-v1",
            ],
            "compatibility": {"participant_runtimes": ["shifter"], "processors": ["raes"], "backends": ["shifter"]},
            "concept_bindings": [{"scope": "implementation_kind", "family": "apparatus-declarations"}],
            "capabilities": {
                "supported_participant_contracts": ["participant-episode-state-envelope-v1"],
                "supported_decision_surface_modes": ["human-supervised"],
                "tool_affordance_expectations": ["http-api"],
                "exposure_policy_kinds": ["observation-stream"],
            },
        }
    )


def native_power_implementation_digest() -> str:
    """Pin the fixed implementation declaration separately from scope and wire versions."""
    return canonical_json_digest(_implementation_manifest().model_dump(mode="json"))


def _implementation(
    participant: str, targets: tuple[str, ...]
) -> tuple[ParticipantImplementationManifestModel, ParticipantImplementationSelectionModel]:
    manifest = _implementation_manifest()
    selected = ParticipantImplementationSelectionModel.model_validate(
        {
            "participant_address": participant,
            "implementation_identity": manifest.identity.model_dump(mode="json"),
            "manifest_ref": NATIVE_POWER_CONTROL_PROFILE_REF,
            "manifest_digest": canonical_json_digest(manifest.model_dump(mode="json")),
            "selected_decision_surface_mode": "human-supervised",
            "participant_contract_versions": ["participant-episode-state-envelope-v1"],
            "exposure_policy": {
                "policy_id": "shifter-native-power-observation-references/v1",
                "exposure_policy_kinds": ["observation-stream"],
                "visibility_scope_refs": list(targets),
            },
        }
    )
    return manifest, selected


def _native_mappings(
    model: RuntimeModel, selection: NativePowerControlSelection, targets: tuple[str, ...]
) -> tuple[NativePowerActionMapping, ...]:
    if selection.pause_action_contract_address == selection.resume_action_contract_address:
        raise ValueError("Installed native action mapping is ambiguous")
    manifest, selected = _implementation(selection.participant_address, targets)
    actions: tuple[tuple[Literal["pause", "resume"], str], ...] = (
        ("pause", selection.pause_action_contract_address),
        ("resume", selection.resume_action_contract_address),
    )
    mappings = tuple(
        NativePowerActionMapping(
            participant_address=selection.participant_address,
            controller_address=selection.controller_address,
            action_contract_address=contract,
            observation_boundary_address=selection.observation_boundary_address,
            target_addresses=targets,
            verb=verb,
            implementation_manifest=manifest,
            implementation_selection=selected,
        )
        for verb, contract in actions
    )
    for mapping in mappings:
        _validate_binding(model, mapping)
    return mappings


def build_native_power_control_candidate(
    *,
    scenario: Scenario,
    context: CompiledParticipantContext,
    coordinates: NativeRuntimeCoordinates,
    power: NativePowerInput,
    selection: NativePowerControlSelection,
    dispatch: ShifterProvisioningDispatchPort,
    port: NativePowerReservationPort,
) -> NativePowerControlCandidate:
    """Validate two exact native meanings and declare only their candidate scope."""
    if coordinates.resource_generation != power.resource_generation or not power.members:
        raise ValueError("Native control candidate generation unavailable")
    model = restore_compiled_model(scenario, context)
    mappings = _power_mappings(model, power, selection)
    bindings = tuple(
        NativePowerActionBinding(
            coordinates=coordinates,
            participant_address=mapping.participant_address,
            controller_address=mapping.controller_address,
            action_contract_address=mapping.action_contract_address,
            observation_boundary_address=mapping.observation_boundary_address,
            target_addresses=mapping.target_addresses,
            verb=mapping.verb,
            implementation_manifest=mapping.implementation_manifest,
            implementation_selection=mapping.implementation_selection,
            compiler_input_digest=context.compiler_input_digest,
        )
        for mapping in mappings
    )
    runtime = NativePowerParticipantRuntime(model=model, bindings=bindings, port=port)
    target = create_shifter_backend_target(port=dispatch, scenario=scenario)
    return NativePowerControlCandidate(_with_native_capabilities(target, runtime), model, bindings)


def _power_mappings(
    model: RuntimeModel, power: NativePowerInput, selection: NativePowerControlSelection
) -> tuple[NativePowerActionMapping, ...]:
    targets = tuple(sorted({member.member_ref.rsplit("#", 1)[0] for member in power.members}))
    if not power.members or set(targets) != set(model.node_deployments):
        raise ValueError("Native control candidate footprint unavailable")
    return _native_mappings(model, selection, targets)


def validate_bound_native_power_configuration(
    *,
    scenario: Scenario,
    context: CompiledParticipantContext,
    power: NativePowerInput,
    selection: NativePowerControlSelection,
) -> None:
    """Check retained private compilation and complete logical footprint, without an owner."""
    _power_mappings(restore_compiled_model(scenario, context), power, selection)


def build_native_power_planning_target(
    *,
    scenario: Scenario,
    context: CompiledParticipantContext,
    selection: NativePowerControlSelection,
    dispatch: ShifterProvisioningDispatchPort,
) -> RuntimeTarget:
    """Validate prospective logical meaning without native generation or effect authority."""
    model = restore_compiled_model(scenario, context)
    _native_mappings(model, selection, tuple(sorted(model.node_deployments)))
    target = create_shifter_backend_target(port=dispatch, scenario=scenario)
    return _with_native_capabilities(target, _PlanningRuntime())


def _with_native_capabilities(target: RuntimeTarget, runtime: BaseParticipantRuntime) -> RuntimeTarget:
    contracts = set(target.manifest.supported_contract_versions) | {
        "participant-episode-state-envelope-v1",
        "participant-episode-history-event-stream-v1",
        "participant-behavior-history-event-stream-v1",
    }
    # The release owns the manifest's allowed IDs and feature prerequisites.
    # The adapter separately requires API-409 wire 2.0.0 for the native path;
    # do not insert an ID that this released manifest validator refuses.
    for scope in PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS.values():
        for feature in _FEATURES:
            contracts.update(scope.get(feature, ()))
    capabilities = ParticipantRuntimeCapabilities(
        name="shifter-native-power-supervision-candidate",
        supported_behavior_features=_FEATURES,
        feature_support=tuple(
            ParticipantFeatureSupport(
                feature=feature,
                support_level=ParticipantFeatureSupportLevel.EXACT,
                evidence_refs=(_CANDIDATE_EVIDENCE,),
            )
            for feature in sorted(_FEATURES)
        ),
    )
    return replace(
        target,
        participant_runtime=runtime,
        manifest=replace(
            target.manifest,
            capabilities=replace(target.manifest.capabilities, participant_runtime=capabilities),
            supported_contract_versions=frozenset(contracts),
        ),
    )
