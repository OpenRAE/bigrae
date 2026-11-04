"""Native request preparation uses exact released declarations, fold and carrier."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from shared.native_participant import NativeControlSubmission
from tests.shared.raes.test_native_participant_actions import admitted as native_admitted
from tests.shared.raes.test_native_participant_actions import installed_action

__all__ = ["installed_action", "native_admitted"]


@pytest.fixture
def admitted(native_admitted, installed_action):
    return SimpleNamespace(case=native_admitted, model=installed_action[1])


def prepare(case, kind, *, expected=None, decision_id=None):
    from shared.raes.native_supervision_cursor import native_supervision_cursor
    from shared.raes.native_supervisory_requests import build_native_power_control_request

    plane, _, binding, action, _, _, _ = case.case
    cursor = native_supervision_cursor(
        model=case.model,
        snapshot=plane.snapshot,
        participant_address=binding.participant_address,
        episode_id="episode:fixture",
    )
    return build_native_power_control_request(
        model=case.model,
        snapshot=plane.snapshot,
        binding=binding,
        episode_id="episode:fixture",
        source_ref="urn:shifter:synthetic-source",
        evidence_ref="fixture:authority",
        submission=NativeControlSubmission(
            kind=kind,
            request_id=uuid4(),
            proposal_id=UUID(action.validated_selection.proposal_ref),
            action_id=UUID(action.action_instance_id),
            expected_cut_digest=expected or cursor.control_cut_digest,
            decision_id=decision_id,
            verb=binding.verb,
        ),
    )


def record(case, request):
    from shared.raes.native_supervisory_requests import parse_native_power_control_request

    plane, _, binding, _, identity, _, _ = case.case
    receipt = plane.record_participant_control(
        binding.participant_address, parse_native_power_control_request(request.intent_json), identity=identity
    )
    status = plane.get_operation(receipt.operation_id)
    assert status.state.value == "succeeded", [
        (diagnostic.code, diagnostic.message) for diagnostic in status.diagnostics
    ]


@pytest.mark.parametrize("decision", ["approval", "denial", "cancellation"])
def test_prepared_native_request_is_accepted_by_the_released_owner(admitted, decision):
    from shared.raes.native_supervisory_requests import parse_native_power_control_request

    proposal = prepare(admitted, "proposal")
    parsed = parse_native_power_control_request(proposal.intent_json)
    assert parsed.application.expected_history_head == 0
    assert parsed.application.effective_order == 1
    assert "fixture:authority" not in repr(proposal)
    record(admitted, proposal)
    decision_request = prepare(admitted, decision)
    decision_intent = parse_native_power_control_request(decision_request.intent_json)
    assert decision_intent.application.expected_history_head == 1
    assert decision_intent.expected_state_revision == 1
    record(admitted, decision_request)
    plane, behavior, _, action, identity, port, _ = admitted.case
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == (
        "succeeded" if decision == "approval" else "failed"
    )
    assert len(port.requests) == (1 if decision == "approval" else 0)


def test_old_expected_cut_cannot_prepare_a_new_request(admitted):
    proposal = prepare(admitted, "proposal")
    record(admitted, proposal)
    with pytest.raises(ValueError, match="Native supervisory request unavailable"):
        prepare(admitted, "approval", expected=proposal.control_cut_digest)


def test_cancelled_approved_proposal_cannot_admit_an_action(admitted):
    from shared.raes.native_supervisory_requests import parse_native_power_control_request

    record(admitted, prepare(admitted, "proposal"))
    approval = prepare(admitted, "approval")
    record(admitted, approval)
    decision = parse_native_power_control_request(approval.intent_json).decision_ref
    record(admitted, prepare(admitted, "cancellation", decision_id=UUID(decision)))
    plane, behavior, _, action, identity, port, _ = admitted.case
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert not port.requests


def test_unknown_native_control_kind_is_never_a_generic_sdk_operation(admitted):
    with pytest.raises(ValueError, match="Native supervisory request unavailable"):
        prepare(admitted, "handoff")


def test_action_request_round_trip_preserves_the_released_typed_carrier(installed_action):
    from shared.raes.native_supervisory_requests import (
        parse_native_power_action_request,
        serialize_native_power_action_request,
    )

    request = installed_action[3]
    restored = parse_native_power_action_request(serialize_native_power_action_request(request))
    assert restored == request
