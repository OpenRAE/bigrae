"""Prepare fixed native supervision through released request and policy models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import TypeAdapter
from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
from raes_contracts.runtime_state import RuntimeSnapshot
from raes_processor.compiler import project_control_episode_policy
from raes_processor.models import RuntimeModel
from raes_processor.models.participant_action_arguments import resolve_participant_action_arguments
from raes_runtime.participant_control_intents import ParticipantControlIntent
from raes_runtime.participant_crossing_intents import action_subject, control_subject

from shared.native_participant import NativeControlCommandRecord, NativeControlSubmission, NativePreparedControlRequest
from shared.raes.native_participant_actions import NativePowerActionBinding, native_power_action_commitment
from shared.raes.native_supervision_cursor import native_supervision_cursor

if TYPE_CHECKING:
    from raes_runtime.control_plane import RuntimeControlPlane

NativeControlKind = Literal["proposal", "approval", "denial", "cancellation"]
_KINDS = frozenset({"proposal", "approval", "denial", "cancellation"})
_INTENTS = TypeAdapter(ParticipantControlIntent)
_ACTIONS = TypeAdapter(ParticipantActionAdmissionRequest)
_UNAVAILABLE = "Native supervisory request unavailable"


def serialize_native_power_action_request(request: ParticipantActionAdmissionRequest) -> bytes:
    """Retain the original released carrier through the standard typed serializer."""
    payload = _ACTIONS.dump_json(request)
    if not 1 <= len(payload) <= 16_384:
        raise ValueError(_UNAVAILABLE)
    return payload


def parse_native_power_action_request(payload: bytes) -> ParticipantActionAdmissionRequest:
    """Restore the original carrier without consulting a newer runtime cut."""
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 16_384:
        raise ValueError(_UNAVAILABLE)
    try:
        return _ACTIONS.validate_json(payload)
    except Exception:  # noqa: BLE001  # native request payloads stay out of parser diagnostics
        raise ValueError(_UNAVAILABLE) from None


def native_power_action_request(
    model: RuntimeModel, binding: NativePowerActionBinding, *, proposal_id: UUID, action_id: UUID
) -> ParticipantActionAdmissionRequest:
    """Bind the installed empty-argument native effect to preallocated identities."""
    contract = model.action_contracts[binding.action_contract_address]
    return ParticipantActionAdmissionRequest(
        participant_address=binding.participant_address,
        action_contract_address=binding.action_contract_address,
        observation_boundary_address=binding.observation_boundary_address,
        action_instance_id=str(action_id),
        implementation_manifest=binding.implementation_manifest,
        implementation_selection=binding.implementation_selection,
        validated_selection=resolve_participant_action_arguments(
            contract,
            action_contract_address=contract.address,
            argument_shape_ref=contract.argument_shape_ref,
            proposal_ref=str(proposal_id),
            proposed_arguments={},
        ),
        target_addresses=binding.target_addresses,
    )


def build_native_power_action_submission(
    *,
    owner: RuntimeControlPlane,
    model: RuntimeModel,
    binding: NativePowerActionBinding,
    episode_id: str,
    proposal_id: UUID,
    action_id: UUID,
    expected_cut_digest: str,
) -> NativePreparedControlRequest:
    """Prepare the exact linked action and SDK-owned crossing subject before submission."""
    cursor = native_supervision_cursor(
        model=model, snapshot=owner.snapshot, participant_address=binding.participant_address, episode_id=episode_id
    )
    if cursor.control_cut_digest != expected_cut_digest:
        raise ValueError(_UNAVAILABLE)
    request = native_power_action_request(model, binding, proposal_id=proposal_id, action_id=action_id)
    return NativePreparedControlRequest(
        serialize_native_power_action_request(request),
        action_subject(owner, request).model_dump_json().encode(),
        cursor.control_cut_digest,
    )


def parse_native_power_control_request(payload: bytes) -> ParticipantControlIntent:
    """Revalidate immutable native request bytes through the released public union."""
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 16_384:
        raise ValueError(_UNAVAILABLE)
    try:
        intent = _INTENTS.validate_json(payload)
    except Exception:  # noqa: BLE001  # private native request bytes never enter parser diagnostics
        raise ValueError(_UNAVAILABLE) from None
    if intent.kind not in _KINDS or intent.application is None:
        raise ValueError(_UNAVAILABLE)
    return intent


def native_power_retry_request(
    command: NativeControlCommandRecord, *, decision_id: UUID | None = None
) -> NativePreparedControlRequest:
    """An exact retry cannot change a cancellation's original native target choice."""
    if command.kind == "cancellation":
        intent = parse_native_power_control_request(command.request.intent_json)
        expected_kind = "decision" if decision_id is not None else "proposal"
        expected_ref = str(decision_id if decision_id is not None else command.proposal_id)
        if intent.target_kind != expected_kind or intent.target_ref != expected_ref:
            raise ValueError(_UNAVAILABLE)
    elif decision_id is not None:
        raise ValueError(_UNAVAILABLE)
    return command.request


def original_native_power_decision(command: NativeControlCommandRecord) -> UUID | None:
    """Recover only the original cancellation target; no current-history selection."""
    decision = None
    if command.kind == "cancellation":
        intent = parse_native_power_control_request(command.request.intent_json)
        if intent.target_kind == "decision":
            decision = UUID(intent.target_ref)
    native_power_retry_request(command, decision_id=decision)
    return decision


def build_native_power_control_request(
    *,
    submission: NativeControlSubmission,
    model: RuntimeModel,
    snapshot: RuntimeSnapshot,
    binding: NativePowerActionBinding,
    episode_id: str,
    source_ref: str,
    evidence_ref: str,
) -> NativePreparedControlRequest:
    """Select one declared transition at the owning fold's exact requested cut.

    These bytes are the original request, not an accepted control occurrence.
    Persist them before SDK submission and reuse them unchanged on an exact
    retry. Neither a client nor a later owner may rebase an existing request.
    """
    kind = submission.kind
    request_id = submission.request_id
    proposal_id = submission.proposal_id
    action_id = submission.action_id
    expected_cut_digest = submission.expected_cut_digest
    decision_id = submission.decision_id
    if (
        kind not in _KINDS
        or (kind != "cancellation" and decision_id is not None)
        or not all(isinstance(value, UUID) and value.int for value in (request_id, proposal_id, action_id))
    ):
        raise ValueError(_UNAVAILABLE)
    cursor = native_supervision_cursor(
        model=model, snapshot=snapshot, participant_address=binding.participant_address, episode_id=episode_id
    )
    if expected_cut_digest != cursor.control_cut_digest:
        raise ValueError(_UNAVAILABLE)
    specifications = [
        spec
        for spec in model.behavior_specifications.values()
        if spec.mixed_control_participant_address == binding.participant_address
    ]
    if len(specifications) != 1:
        raise ValueError(_UNAVAILABLE)
    policy = project_control_episode_policy(model, specifications[0].address, episode_id=episode_id)
    state = policy.state(cursor.state_ref)
    transitions = [item for item in policy.transitions if item.kind == kind and item.from_state_ref == cursor.state_ref]
    if state is None or state.controller_ref != binding.controller_address or len(transitions) != 1:
        raise ValueError(_UNAVAILABLE)
    payload = {
        "kind": kind,
        "declaration_ref": transitions[0].transition_ref,
        "episode_id": episode_id,
        "client_correlation_id": str(request_id),
        "policy_revision": cursor.policy_revision,
        "expected_state_revision": cursor.state_revision,
        "provenance_refs": [source_ref],
        "evidence_refs": [evidence_ref],
        "object_marking_refs": ["shifter:native-control-references/v1"],
        "limitation_refs": ["shifter:dedicated-gce-native-power/v1"],
        "application": {
            "semantics": "mixed-control-policy-occurrence/rev1",
            "policy_ref": cursor.policy_ref,
            "prior_state_ref": cursor.state_ref,
            "expected_history_head": cursor.history_head,
            "effective_order": cursor.next_order,
        },
    }
    if kind == "proposal":
        action = native_power_action_request(model, binding, proposal_id=proposal_id, action_id=action_id)
        payload.update(
            proposal_id=str(proposal_id),
            proposal_revision=1,
            action_contract_ref=binding.action_contract_address,
            payload_digest=native_power_action_commitment(binding, action, episode_id),
        )
    elif kind in {"approval", "denial"}:
        payload.update(
            proposal_ref=str(proposal_id), proposal_revision=1, decision_ref=str(request_id), decision_revision=1
        )
    else:
        if decision_id is not None and (not isinstance(decision_id, UUID) or not decision_id.int):
            raise ValueError(_UNAVAILABLE)
        payload.update(
            target_kind="decision" if decision_id is not None else "proposal",
            target_ref=str(decision_id if decision_id is not None else proposal_id),
            target_revision=1,
        )
    intent = _INTENTS.validate_python(payload)
    intent_json = intent.model_dump_json().encode()
    parse_native_power_control_request(intent_json)
    return NativePreparedControlRequest(
        intent_json,
        control_subject(binding.participant_address, intent).model_dump_json().encode(),
        cursor.control_cut_digest,
    )
