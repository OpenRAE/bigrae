"""Validate native request identity through released carriers, without interpretation outside this layer."""

from uuid import UUID

from raes_contracts.contracts.participant_crossing import ParticipantCrossingSubjectReferenceModel
from raes_runtime.participant_crossing_intents import control_subject

from shared.native_participant import (
    NativeControlSubmission,
    NativePowerControlSelection,
    NativePreparedControlRequest,
    NativeRuntimeCoordinates,
)
from shared.raes.native_supervisory_requests import (
    parse_native_power_action_request,
    parse_native_power_control_request,
)

_UNAVAILABLE = "Native participant request unavailable"


def validate_prepared_native_power_request(
    request: NativePreparedControlRequest,
    *,
    submission: NativeControlSubmission,
    coordinates: NativeRuntimeCoordinates,
    selection: NativePowerControlSelection,
    allowed_decision_ids: frozenset[UUID] = frozenset(),
) -> None:
    """Check opaque request and subject identity before native durable admission.

    Full portable eligibility, approval meaning and outcome remain with the
    released owner and installed adapter. A well-formed request is no permit.
    """
    request_id = submission.request_id
    kind = submission.kind
    verb = submission.verb
    proposal_id = submission.proposal_id
    action_id = submission.action_id
    try:
        if (
            not isinstance(request, NativePreparedControlRequest)
            or not all(isinstance(value, UUID) and value.int for value in (request_id, proposal_id, action_id))
            or verb not in {"pause", "resume"}
            or not 1 <= len(request.subject_json) <= 4096
        ):
            raise ValueError(_UNAVAILABLE)
        episode = f"episode:{coordinates.run_id}"
        contract = (
            selection.pause_action_contract_address if verb == "pause" else selection.resume_action_contract_address
        )
        subject = ParticipantCrossingSubjectReferenceModel.model_validate_json(request.subject_json)
        if subject.participant_address != selection.participant_address or subject.episode_id != episode:
            raise ValueError(_UNAVAILABLE)
        if kind == "action":
            _validate_action_identity(request, submission, selection, subject, episode, contract)
            return
        _validate_control_identity(request, submission, selection, subject, episode, contract, allowed_decision_ids)
    except Exception:  # noqa: BLE001  # serialized native request data never enters public diagnostics
        raise ValueError(_UNAVAILABLE) from None


def _validate_action_identity(
    request: NativePreparedControlRequest,
    submission: NativeControlSubmission,
    selection: NativePowerControlSelection,
    subject: ParticipantCrossingSubjectReferenceModel,
    episode: str,
    contract: str,
) -> None:
    """Keep the preallocated action and complete logical meaning bound to its proposal."""
    request_id, action_id, proposal_id = submission.request_id, submission.action_id, submission.proposal_id
    action = parse_native_power_action_request(request.intent_json)
    if (
        request_id != action_id
        or action.action_instance_id != str(action_id)
        or action.participant_address != selection.participant_address
        or action.action_contract_address != contract
        or action.observation_boundary_address != selection.observation_boundary_address
        or action.validated_selection is None
        or action.validated_selection.proposal_ref != str(proposal_id)
        or subject.contract_id != "participant-action-admission-v1"
        or subject.subject_ref != f"participant-action-admission:{selection.participant_address}:{episode}:{action_id}"
    ):
        raise ValueError(_UNAVAILABLE)


def _validate_control_identity(
    request: NativePreparedControlRequest,
    submission: NativeControlSubmission,
    selection: NativePowerControlSelection,
    subject: ParticipantCrossingSubjectReferenceModel,
    episode: str,
    contract: str,
    allowed_decision_ids: frozenset[UUID],
) -> None:
    """Validate original proposal, decision, and cancellation targets through released carriers."""
    kind, request_id, proposal_id = submission.kind, submission.request_id, submission.proposal_id
    intent = parse_native_power_control_request(request.intent_json)
    if (
        intent.kind != kind
        or intent.client_correlation_id != str(request_id)
        or intent.episode_id != episode
        or subject != control_subject(selection.participant_address, intent)
    ):
        raise ValueError(_UNAVAILABLE)
    if kind == "proposal":
        if (
            request_id != proposal_id
            or intent.proposal_id != str(proposal_id)
            or intent.action_contract_ref != contract
        ):
            raise ValueError(_UNAVAILABLE)
    elif kind in {"approval", "denial"}:
        if intent.proposal_ref != str(proposal_id) or intent.decision_ref != str(request_id):
            raise ValueError(_UNAVAILABLE)
    elif kind == "cancellation":
        if (
            (intent.target_kind == "proposal" and intent.target_ref != str(proposal_id))
            or (intent.target_kind == "decision" and UUID(intent.target_ref) not in allowed_decision_ids)
            or intent.target_kind not in {"proposal", "decision"}
        ):
            raise ValueError(_UNAVAILABLE)
    else:
        raise ValueError(_UNAVAILABLE)
