"""Synthetic released supervisory crossings precede native reservations."""

from dataclasses import replace

import pytest
from raes_backend_protocols.capabilities import (
    PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS,
    ParticipantFeatureSupport,
)
from raes_contracts.contracts.participant_crossing import ParticipantCrossingGateDisposition as Gate
from raes_contracts.contracts.participant_crossing import ParticipantCrossingPolicyReferenceModel
from raes_contracts.vocabulary import ParticipantFeatureSupportLevel
from raes_runtime.control_plane_security import ControlPlaneIdentity, ControlPlaneRole, ParticipantControlSubjectBinding
from raes_runtime.participant_crossing_mediation import (
    ParticipantCrossingEvidence,
    ParticipantCrossingPolicyResolution,
    ParticipantCrossingSemanticGates,
    ParticipantCrossingValidationContext,
)

from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import NativeControlPlaneConfiguration, create_native_control_plane
from tests.shared.raes.test_native_control_plane import _target
from tests.shared.raes.test_native_participant_actions import _control, installed_action

__all__ = ["installed_action"]
_FEATURES = {"participant_ingress_admission", "participant_intervention"}
_EVIDENCE = "fixture:crossing-evidence"


class _CrossingOwner:
    """The fixture supplies policy; SDK checks identity and capability."""

    deny = False

    def __init__(self):
        self.subjects = []
        self.authorities = set()
        self.evidence = {_EVIDENCE}
        self.policy = ParticipantCrossingPolicyReferenceModel(
            policy_id="fixture:crossing-policy",
            policy_revision="1",
            policy_digest="sha256:" + "a" * 64,
            policy_decision_ref="fixture:policy-decision",
            decision_cut_ref="fixture:policy-cut",
            effective_order=0,
            valid_from_order=0,
            valid_until_order=1000,
        )

    def resolve(self, intent, snapshot):
        self.subjects.append(intent.subject)
        self.authorities.update(intent.authority_basis_refs)
        self.evidence.update(intent.evidence_refs)
        self.evidence.update(intent.required_evidence_refs)
        return ParticipantCrossingPolicyResolution(
            policy=self.policy,
            gates=ParticipantCrossingSemanticGates(
                participant_authority=Gate.PERMIT,
                action_admission=Gate.DENY if self.deny else Gate.PERMIT,
                visibility=Gate.NOT_APPLICABLE,
                marking_authorization=Gate.PERMIT,
                declassification=Gate.NOT_APPLICABLE,
                transformation_validity=Gate.NOT_APPLICABLE,
            ),
            reason_code="policy-satisfied",
        )

    def validation_context(self, snapshot, participant_address):
        return ParticipantCrossingValidationContext(
            known_subjects=tuple(self.subjects),
            policies=(self.policy,),
            known_evidence_refs=frozenset(self.evidence),
            known_authority_basis_refs=frozenset(self.authorities),
        )


def _governed_target(scenario, runtime):
    target = _target(scenario)
    declarations = tuple(
        ParticipantFeatureSupport(
            feature=feature, support_level=ParticipantFeatureSupportLevel.EXACT, evidence_refs=(_EVIDENCE,)
        )
        for feature in sorted(_FEATURES)
    )
    contracts = set(target.manifest.supported_contract_versions)
    for scope in PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS.values():
        for feature in _FEATURES:
            contracts.update(scope.get(feature, ()))
    capabilities = replace(
        target.manifest.participant_runtime,
        supported_behavior_features=frozenset(_FEATURES),
        feature_support=declarations,
    )
    return replace(
        target,
        participant_runtime=runtime,
        manifest=replace(
            target.manifest,
            supported_contract_versions=frozenset(contracts),
            capabilities=replace(target.manifest.capabilities, participant_runtime=capabilities),
        ),
    )


def _crossing_evidence():
    return ParticipantCrossingEvidence(
        audience_scope_ref="fixture:organizer-audience",
        required_evidence_refs=[_EVIDENCE],
        provenance_refs=["fixture:source"],
        evidence_refs=[_EVIDENCE],
        object_marking_refs=["fixture:synthetic"],
        authorization_scope="fixture:organizer",
        loss_and_limitations=["fixture:synthetic-only"],
    )


@pytest.mark.parametrize("condition", ["current", "denied", "revoked"])
def test_governed_supervision_reserves_only_after_current_crossing_admission(installed_action, tmp_path, condition):
    scenario, model, binding, action, port, runtime = installed_action
    crossing = _CrossingOwner()
    evidence = _crossing_evidence()
    owner = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=_governed_target(scenario, runtime),
            scenario=scenario,
            context=project_compiled_participants(model),
            store_root=tmp_path,
            coordinates=binding.coordinates,
            resolver=port.resolver,
            crossing_policy_resolver=crossing,
            enforce_final_sink_flow_control=False,
        )
    ).owner
    identity = ControlPlaneIdentity(
        identity="fixture:organizer",
        target_name=owner.target_name,
        roles=frozenset({ControlPlaneRole.OPERATOR}),
        participant_control_subjects=(
            ParticipantControlSubjectBinding(binding.participant_address, binding.controller_address),
        ),
    )
    try:
        owner.initialize_participant_episode(
            binding.participant_address, episode_id="episode:fixture", identity=identity
        )
        _control(owner, binding, action, identity, crossing_evidence=evidence)
        crossing.deny = condition == "denied"
        port.resolver.revoked = condition == "revoked"
        receipt = owner.admit_participant_action(
            model.participant_behaviors[binding.participant_address],
            action,
            identity=identity,
            crossing_evidence=evidence,
            idempotency_key="fixture:action",
        )
        assert owner.get_operation(receipt.operation_id).state.value == (
            "succeeded" if condition == "current" else "failed"
        )
        assert len(port.requests) == (1 if condition == "current" else 0)
        assert owner.snapshot.participant_crossing_history[binding.participant_address]
        assert not owner.snapshot.participant_control_evaluation_history
    finally:
        owner.close()


def test_required_flow_control_does_not_silently_fall_back(installed_action, tmp_path):
    scenario, model, binding, _, port, runtime = installed_action
    options = {
        "target": _governed_target(scenario, runtime),
        "scenario": scenario,
        "context": project_compiled_participants(model),
        "store_root": tmp_path,
        "coordinates": binding.coordinates,
        "resolver": port.resolver,
        "crossing_policy_resolver": _CrossingOwner(),
    }
    with pytest.raises(ValueError, match="final-sink flow-control enforcement"):
        create_native_control_plane(NativeControlPlaneConfiguration(**options))
    # Failed construction releases only its own store lease. A separately
    # selected API-423-only composition can then acquire that same store.
    with create_native_control_plane(
        NativeControlPlaneConfiguration(**options, enforce_final_sink_flow_control=False)
    ).owner as owner:
        assert not owner.snapshot.participant_control_evaluation_history


def test_native_invocation_identity_is_stable_for_one_operation_and_member():
    from uuid import uuid4

    from shared.native_participant import native_power_invocation_id

    operation = uuid4()
    first = native_power_invocation_id(operation, "provision.node.web#0")
    assert first == native_power_invocation_id(operation, "provision.node.web#0")
    assert first != native_power_invocation_id(operation, "provision.node.web#1")
    assert first != native_power_invocation_id(uuid4(), "provision.node.web#0")
    assert first.int != 0
