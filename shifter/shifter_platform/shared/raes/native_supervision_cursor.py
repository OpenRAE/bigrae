"""Prepare native product requests through the released owning control fold."""

from __future__ import annotations

from raes_contracts.contracts import fold_participant_control_episode_v2
from raes_contracts.contracts.participant_control_occurrence_v2 import (
    ParticipantControlOccurrenceV2Model,
    parse_participant_control_occurrence,
)
from raes_contracts.runtime_state import RuntimeSnapshot
from raes_processor.compiler import project_control_episode_policy
from raes_processor.models import RuntimeModel

from shared.native_participant import NativeSupervisionCursor
from shared.raes.native_participant_actions import MAX_NATIVE_CONTROL_RECORDS, native_participant_control_cut

_UNAVAILABLE = "Native supervisory request coordinates unavailable"


def native_supervision_cursor(
    *,
    model: RuntimeModel,
    snapshot: RuntimeSnapshot,
    participant_address: str,
    episode_id: str,
) -> NativeSupervisionCursor:
    """Fold exact current-episode history under its immutable compiler context.

    The caller supplies the generation-bound original model, not today's source
    or a policy dictionary. This projection never grants authority, advances
    state, chooses a controller or replaces the runtime's admission checks.
    """
    episode = snapshot.participant_episode_results.get(participant_address, {})
    specifications = [
        specification
        for specification in model.behavior_specifications.values()
        if specification.mixed_control_participant_address == participant_address
    ]
    if episode.get("episode_id") != episode_id or episode.get("status") != "running" or len(specifications) != 1:
        raise ValueError(_UNAVAILABLE)
    history = snapshot.participant_control_history.get(participant_address, ())
    if len(history) >= MAX_NATIVE_CONTROL_RECORDS:
        raise ValueError(_UNAVAILABLE)
    records = []
    for payload in history:
        record = parse_participant_control_occurrence(payload)
        if record.participant_address != participant_address:
            raise ValueError(_UNAVAILABLE)
        if record.episode_id != episode_id:
            continue
        if not isinstance(record, ParticipantControlOccurrenceV2Model):
            raise ValueError(_UNAVAILABLE)
        records.append(record)
    policy = project_control_episode_policy(model, specifications[0].address, episode_id=episode_id)
    if policy.pin.form != "reusable-policy":
        raise ValueError(_UNAVAILABLE)
    folded = fold_participant_control_episode_v2(records, policy=policy)
    if folded.violation is not None:
        raise ValueError(_UNAVAILABLE)
    state = folded.state
    return NativeSupervisionCursor(
        episode_id=episode_id,
        policy_ref=policy.pin.policy_ref,
        policy_revision=policy.pin.policy_revision,
        state_ref=state.state_ref,
        state_revision=state.state_revision,
        history_head=len(history),
        next_order=(state.last_order or 0) + 1,
        control_cut_digest=native_participant_control_cut(snapshot, participant_address, episode_id),
    )
