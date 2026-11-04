"""Product request coordinates use the released owning episode fold."""

from copy import deepcopy

import pytest

from tests.shared.raes.test_native_participant_actions import _cancel_approval, _control, admitted, installed_action

__all__ = ["admitted", "installed_action"]


def cursor(admitted, model, snapshot=None):
    from shared.raes.native_supervision_cursor import native_supervision_cursor

    owner, _, binding, _, _, _, _ = admitted
    return native_supervision_cursor(
        model=model,
        snapshot=owner.snapshot if snapshot is None else snapshot,
        participant_address=binding.participant_address,
        episode_id="episode:fixture",
    )


def test_proposal_approval_and_cancellation_have_separate_exact_cursor_positions(admitted, installed_action):
    owner, _, binding, action, identity, _, _ = admitted
    first = cursor(admitted, installed_action[1])
    assert (first.state_revision, first.history_head, first.next_order) == (0, 0, 1)
    _control(owner, binding, action, identity)
    approved = cursor(admitted, installed_action[1])
    assert (approved.state_revision, approved.history_head, approved.next_order) == (2, 2, 3)
    assert first.control_cut_digest != approved.control_cut_digest
    _cancel_approval(owner, identity)
    cancelled = cursor(admitted, installed_action[1])
    assert (cancelled.state_revision, cancelled.history_head, cancelled.next_order) == (3, 3, 4)


@pytest.mark.parametrize("fault", ["revision", "participant", "policy", "episode"])
def test_invalid_control_history_has_no_product_cursor(admitted, installed_action, fault):
    owner, _, binding, action, identity, _, _ = admitted
    _control(owner, binding, action, identity)
    snapshot = deepcopy(owner.snapshot)
    if fault == "episode":
        snapshot.participant_episode_results[binding.participant_address]["status"] = "terminated"
    else:
        history = [deepcopy(record) for record in snapshot.participant_control_history[binding.participant_address]]
        record = history[-1]
        if fault == "revision":
            record["occurrence"]["resulting_state_revision"] = 99
        elif fault == "participant":
            record["participant_address"] = "participant.behavior.foreign"
        else:
            record["policy"]["policy_revision"] = "foreign"
        snapshot.participant_control_history = {binding.participant_address: history}
    with pytest.raises(ValueError):
        cursor(admitted, installed_action[1], snapshot)


def test_rejected_attempt_advances_history_without_advancing_state_or_order(admitted, installed_action):
    from uuid import uuid4

    from raes_runtime.participant_control_intents import ParticipantApprovalControlIntent

    owner, _, binding, action, identity, _, _ = admitted
    _control(owner, binding, action, identity, approve=False)
    position = cursor(admitted, installed_action[1])
    assert (position.state_revision, position.history_head, position.next_order) == (1, 1, 2)
    owner.record_participant_control(
        binding.participant_address,
        ParticipantApprovalControlIntent(
            declaration_ref="participant.behavior-specification.controlled.permitted-transition.approve",
            episode_id=position.episode_id,
            client_correlation_id="fixture:stale-approval",
            policy_revision=position.policy_revision,
            expected_state_revision=0,
            provenance_refs=["fixture:source"],
            evidence_refs=["fixture:authority"],
            object_marking_refs=["fixture:synthetic"],
            limitation_refs=["fixture:bounded"],
            proposal_ref=action.validated_selection.proposal_ref,
            proposal_revision=1,
            decision_ref=str(uuid4()),
            decision_revision=1,
            application={
                "semantics": "mixed-control-policy-occurrence/rev1",
                "policy_ref": position.policy_ref,
                "prior_state_ref": position.state_ref,
                "expected_history_head": position.history_head,
                "effective_order": position.next_order,
            },
        ),
        identity=identity,
    )
    after = cursor(admitted, installed_action[1])
    assert (after.state_revision, after.history_head, after.next_order) == (1, 2, 2)
    assert after.control_cut_digest != position.control_cut_digest
