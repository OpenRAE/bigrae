"""Closed native reservation adapter for released reusable participant control.

The SDK owns live policy folding and action admission. This adapter closes its
optional linkage paths: every native request needs an accepted v2 proposal,
an explicit decision, and an exact commitment to the installed action meaning.
The native port must reserve without dispatch. Only the owning service can
release that reservation after the SDK has durably committed admission.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Literal, Protocol
from uuid import UUID

from raes_backend_protocols.participant_runtime_base import BaseParticipantRuntime
from raes_contracts.canonical import canonical_json_digest
from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
from raes_contracts.contracts.participant_control_occurrence_v2 import parse_participant_control_occurrence
from raes_contracts.contracts.participant_manifests import (
    ParticipantImplementationManifestModel,
    ParticipantImplementationSelectionModel,
)
from raes_contracts.contracts.participant_runtime import ParticipantActionResultModel
from raes_contracts.diagnostics import Diagnostic
from raes_contracts.participant_native_execution import ParticipantNativeActionExecution
from raes_contracts.runtime_state import ApplyResult, RuntimeSnapshot
from raes_processor.compiler import compile_runtime_model
from raes_processor.models import RuntimeModel
from raes_processor.models.participant_action_arguments import resolve_participant_action_arguments

from shared.native_participant import NativeParticipantPowerAction, NativeRuntimeCoordinates

MAX_NATIVE_CONTROL_RECORDS = 256


class NativePowerReservationPort(Protocol):
    """Owning native service: authorize, audit and reserve, without dispatch."""

    def reserve(self, action: NativeParticipantPowerAction) -> UUID:
        """Reserve exact native work without granting launch or cloud permission."""
        ...


@dataclass(frozen=True, slots=True)
class NativePowerActionMapping:
    """Logical native meaning selected by installation, without resource authority."""

    participant_address: str
    controller_address: str
    action_contract_address: str
    observation_boundary_address: str
    target_addresses: tuple[str, ...]
    verb: Literal["pause", "resume"]
    implementation_manifest: ParticipantImplementationManifestModel
    implementation_selection: ParticipantImplementationSelectionModel


@dataclass(frozen=True, slots=True)
class NativePowerActionBinding(NativePowerActionMapping):
    """A logical mapping joined to one qualified native generation and run."""

    coordinates: NativeRuntimeCoordinates
    compiler_input_digest: str = field(repr=False)


def _native_action(
    binding: NativePowerActionBinding,
    request: ParticipantActionAdmissionRequest,
    episode_id: str,
    *,
    control_cut_digest: str = "",
    approval_ref: str = "",
) -> NativeParticipantPowerAction:
    selection = request.validated_selection
    if selection is None:
        raise ValueError("Native action selection is unavailable")
    if str(UUID(request.action_instance_id)) != request.action_instance_id:
        raise ValueError("Native action identity is unavailable")
    if str(UUID(selection.proposal_ref)) != selection.proposal_ref:
        raise ValueError("Native proposal identity is unavailable")
    return NativeParticipantPowerAction(
        coordinates=binding.coordinates,
        participant_address=binding.participant_address,
        controller_address=binding.controller_address,
        episode_id=episode_id,
        action_id=request.action_instance_id,
        proposal_ref=selection.proposal_ref,
        action_contract_address=binding.action_contract_address,
        observation_boundary_address=binding.observation_boundary_address,
        target_addresses=binding.target_addresses,
        verb=binding.verb,
        implementation_selection_digest=canonical_json_digest(binding.implementation_selection.model_dump(mode="json")),
        compiler_input_digest=binding.compiler_input_digest,
        control_cut_digest=control_cut_digest,
        approval_ref=approval_ref,
    )


def native_power_action_commitment(
    binding: NativePowerActionBinding, request: ParticipantActionAdmissionRequest, episode_id: str
) -> str:
    """Bind approval to one native meaning, including its preallocated action ID."""
    action = asdict(_native_action(binding, request, episode_id))
    # The opaque native binding pins private compiler input. A portable digest
    # must not become an offline oracle for private parameter selections.
    action.pop("compiler_input_digest")
    action.pop("control_cut_digest")
    # The decision reference does not exist when the proposal is prepared.
    # The decision binds this proposal digest; native effect metadata separately
    # retains its exact accepted reference and original reviewing proof.
    action.pop("approval_ref")
    action["coordinates"] = {name: str(value) for name, value in asdict(binding.coordinates).items()}
    return canonical_json_digest(
        {
            "contract": "shifter-native-power-action/v1",
            "profile": "shifter-ctf-gce-range-lifecycle",
            "profile_version": "1",
            "action": action,
        }
    )


def native_participant_control_cut(snapshot: RuntimeSnapshot, participant_address: str, episode_id: str) -> str:
    """Pin native work to the SDK's public episode and control history cut.

    This is a native correlation digest, not a policy fold or an authorization
    decision. Behavior events from this action do not alter its approval cut.
    """
    episode = snapshot.participant_episode_results.get(participant_address)
    history = snapshot.participant_control_history.get(participant_address, ())
    if not isinstance(episode, dict) or episode.get("episode_id") != episode_id:
        raise ValueError("Native participant episode is unavailable")
    if len(history) > MAX_NATIVE_CONTROL_RECORDS:
        raise ValueError("Native control history budget is exhausted")
    return canonical_json_digest(
        {
            "contract": "shifter-native-control-cut/v1",
            "participant_address": participant_address,
            "episode": episode,
            "control_history": list(history),
        }
    )


def _validate_binding(model: RuntimeModel, binding: NativePowerActionMapping) -> None:
    behavior = model.participant_behaviors.get(binding.participant_address)
    contract = model.action_contracts.get(binding.action_contract_address)
    policies = [
        spec
        for spec in model.behavior_specifications.values()
        if spec.mixed_control_participant_address == binding.participant_address
    ]
    if (
        binding.verb not in {"pause", "resume"}
        or behavior is None
        or contract is None
        or binding.action_contract_address not in behavior.action_contract_addresses
        or binding.observation_boundary_address not in behavior.observation_boundary_addresses
        or not binding.target_addresses
        or len(set(binding.target_addresses)) != len(binding.target_addresses)
        or not set(binding.target_addresses) <= set(model.node_deployments)
        or not set(binding.target_addresses) <= set(behavior.operating_scope_addresses)
        or len(policies) != 1
        or policies[0].mixed_control_policy is None
        or policies[0].mixed_control_policy.form != "reusable-policy"
        or not any(state.controller_address == binding.controller_address for state in policies[0].controller_states)
        or contract.argument_definitions
        or contract.semantic_version != "1.0.0"
        or contract.spec.get("realization_profile") != "shifter-native-operation-admission-v1"
        or set(contract.effect_classes) != {"evidence_effect"}
        or contract.temporal_contract_ids
        or contract.interaction_classes
        or binding.implementation_manifest.implementation_kind != "human-control-proxy"
        or binding.implementation_selection.participant_address != binding.participant_address
        or binding.implementation_selection.selected_decision_surface_mode != "human-supervised"
    ):
        raise ValueError("Installed native action binding is unavailable")


def _require_proposal(
    binding: NativePowerActionBinding,
    request: ParticipantActionAdmissionRequest,
    snapshot: RuntimeSnapshot,
    episode_id: str,
) -> str:
    payloads = snapshot.participant_control_history.get(binding.participant_address, ())
    if len(payloads) > MAX_NATIVE_CONTROL_RECORDS:
        raise ValueError("Native control history budget is exhausted")
    records = [parse_participant_control_occurrence(payload) for payload in payloads]
    current = [record for record in records if record.episode_id == episode_id]
    if any(record.schema_version != "2.0.0" for record in current):
        raise ValueError("Reusable native proposal is unavailable")
    proposal_ref = request.validated_selection.proposal_ref
    proposals = [
        record.occurrence
        for record in current
        if record.occurrence.disposition == "accepted"
        and record.occurrence.kind == "proposal"
        and record.occurrence.proposal_id == proposal_ref
    ]
    if len(proposals) != 1:
        raise ValueError("Reusable native proposal is unavailable")
    proposal = proposals[0]
    approvals = [
        record.occurrence
        for record in current
        if record.occurrence.disposition == "accepted"
        and record.occurrence.kind == "approval"
        and record.occurrence.proposal_ref == proposal_ref
        and record.occurrence.proposal_revision == proposal.proposal_revision
        and record.occurrence.controller_ref == binding.controller_address
    ]
    if (
        proposal.action_contract_ref != binding.action_contract_address
        or proposal.payload_digest != native_power_action_commitment(binding, request, episode_id)
        or len(approvals) != 1
    ):
        raise ValueError("Approved native action meaning is unavailable")
    approval_ref = approvals[0].decision_ref
    if str(UUID(approval_ref)) != approval_ref or not UUID(approval_ref).int:
        raise ValueError("Approved native action reference is unavailable")
    return approval_ref


class NativePowerParticipantRuntime(BaseParticipantRuntime):
    """Reserve exact native work; never claim asynchronous admission applied it."""

    def __init__(
        self, *, model: RuntimeModel, bindings: tuple[NativePowerActionBinding, ...], port: NativePowerReservationPort
    ) -> None:
        super().__init__()
        if (
            not bindings
            or len(bindings) > 2
            or any(not isinstance(binding, NativePowerActionBinding) for binding in bindings)
            or len({b.action_contract_address for b in bindings}) != len(bindings)
        ):
            raise ValueError("Installed native action binding is unavailable")
        first = bindings[0]
        if len({binding.verb for binding in bindings}) != len(bindings) or any(
            replace(binding, action_contract_address=first.action_contract_address, verb=first.verb) != first
            for binding in bindings
        ):
            raise ValueError("Installed native action binding is unavailable")
        if model.realization_instance is None:
            raise ValueError("Native action compiler context is unavailable")
        model = compile_runtime_model(model.realization_instance)
        compiler_digest = canonical_json_digest(model.realization_instance.model_dump(mode="json"))
        self._bindings = {binding.action_contract_address: deepcopy(binding) for binding in bindings}
        self._contracts = {}
        for binding in self._bindings.values():
            if binding.compiler_input_digest != compiler_digest:
                raise ValueError("Native action compiler context is unavailable")
            _validate_binding(model, binding)
            self._contracts[binding.action_contract_address] = deepcopy(
                model.action_contracts[binding.action_contract_address]
            )
        self._port = port

    def _model_action(
        self, request: ParticipantActionAdmissionRequest, snapshot: RuntimeSnapshot, *, episode_id: str
    ) -> ParticipantNativeActionExecution:
        try:
            binding = self._bindings[request.action_contract_address]
            self._require_exact_request(binding, request)
            approval_ref = _require_proposal(binding, request, snapshot, episode_id)
            action = _native_action(
                binding,
                request,
                episode_id,
                control_cut_digest=native_participant_control_cut(snapshot, binding.participant_address, episode_id),
                approval_ref=approval_ref,
            )
            operation_id = self._port.reserve(action)
            if not isinstance(operation_id, UUID):
                raise ValueError("Native operation reservation is unavailable")
        except Exception:  # noqa: BLE001  # native faults and rejected coordinates never enter portable records
            return ParticipantNativeActionExecution(
                apply_result=ApplyResult(
                    success=False,
                    snapshot=snapshot,
                    diagnostics=[
                        Diagnostic(
                            code="shifter.native-action.withheld",
                            domain="runtime",
                            address=request.participant_address,
                            message="Native action reservation was withheld.",
                        )
                    ],
                )
            )
        result = ParticipantActionResultModel(
            status="accepted",
            participant_address=request.participant_address,
            episode_id=episode_id,
            action_instance_id=request.action_instance_id,
            action_contract_address=request.action_contract_address,
            observation_point=request.observation_boundary_address,
        )
        return ParticipantNativeActionExecution(
            apply_result=ApplyResult(success=True, snapshot=snapshot), action_result=result
        )

    def _require_exact_request(
        self, binding: NativePowerActionBinding, request: ParticipantActionAdmissionRequest
    ) -> None:
        if (
            request.participant_address != binding.participant_address
            or request.observation_boundary_address != binding.observation_boundary_address
            or request.target_addresses != binding.target_addresses
            or request.implementation_manifest != binding.implementation_manifest
            or request.implementation_selection != binding.implementation_selection
            or request.validated_selection is None
            or request.action_result is not None
            or request.post_state_digest is not None
            or request.requires_terminal_outcome
            or request.state_transition_kind != "participant_action_admitted"
            or request.evidence_refs
            or request.visible_refs
            or request.disclosed_refs
            or request.observation_boundary_evidence_refs
            or request.temporal_contexts
            or request.temporal_evidence
            or request.execution_scope_ref is not None
            or request.resource_measurement_requirements
        ):
            raise ValueError("Installed native action request is unavailable")
        contract = self._contracts[binding.action_contract_address]
        expected = resolve_participant_action_arguments(
            contract,
            action_contract_address=contract.address,
            argument_shape_ref=contract.argument_shape_ref,
            proposal_ref=request.validated_selection.proposal_ref,
            proposed_arguments={},
        )
        if request.validated_selection != expected:
            raise ValueError("Installed native action arguments are unavailable")
