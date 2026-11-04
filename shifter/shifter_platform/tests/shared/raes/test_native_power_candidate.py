"""A selected native target is qualified separately from generic provisioning."""

from dataclasses import replace
from uuid import uuid4

import pytest

from shared.native_power import parse_gce_power_incarnation, parse_gce_power_target
from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import NativeControlPlaneConfiguration
from shared.raes.power_input import NativePowerInput, NativePowerMember
from tests.shared.raes.test_native_control_plane import _UnusedDispatch
from tests.shared.raes.test_native_participant_actions import admitted, installed_action

__all__ = ["admitted", "installed_action"]


def candidate_configuration(installed, **changes):
    from shared.native_participant import NativePowerControlSelection

    scenario, model, binding, _, port, _ = installed
    target = parse_gce_power_target(
        {
            "backend": "gce",
            "project_id": "synthetic-project",
            "zone": "europe-west3-a",
            "instance_name": "synthetic-web",
            "bootstrap_capability": "standard",
        },
        instance_id="synthetic-web",
    )
    incarnation = parse_gce_power_incarnation(
        {"instance_identity": "123", "disks": [{"name": "synthetic-root", "identity": "456"}]}
    )
    config = {
        "scenario": scenario,
        "context": project_compiled_participants(model),
        "coordinates": binding.coordinates,
        "power": NativePowerInput(
            binding.coordinates.resource_generation, (NativePowerMember("provision.node.web#0", target, incarnation),)
        ),
        "selection": NativePowerControlSelection(
            participant_address=binding.participant_address,
            controller_address=binding.controller_address,
            pause_action_contract_address="participant.action-contract.request-pause",
            resume_action_contract_address="participant.action-contract.request-resume",
            observation_boundary_address=binding.observation_boundary_address,
        ),
        "dispatch": _UnusedDispatch(),
        "port": port,
    }
    config.update(changes)
    return config


def candidate(installed, **changes):
    from shared.raes.native_power_candidate import build_native_power_control_candidate

    return build_native_power_control_candidate(**candidate_configuration(installed, **changes))


def test_candidate_installs_only_two_closed_native_action_bindings(installed_action):
    from shared.raes.runtime_target import create_shifter_backend_target

    before = create_shifter_backend_target(port=_UnusedDispatch()).manifest
    built = candidate(installed_action)
    assert {binding.verb for binding in built.bindings} == {"pause", "resume"}
    assert built.target.participant_runtime is not None
    assert "participant-control-occurrence-v1" in built.target.manifest.supported_contract_versions
    assert installed_action[0].name not in repr(built)
    assert built.target.manifest.participant_runtime.supported_behavior_features == frozenset(
        {
            "participant_ingress_admission",
            "participant_intervention",
        }
    )
    assert not built.target.manifest.participant_runtime.supports_autonomous_execution
    assert create_shifter_backend_target(port=_UnusedDispatch()).manifest == before


def test_foreign_generation_cannot_construct_a_native_candidate(installed_action):
    with pytest.raises(ValueError):
        candidate(installed_action, coordinates=replace(installed_action[2].coordinates, resource_generation=uuid4()))


def test_unknown_action_meaning_cannot_construct_a_native_candidate(installed_action):
    from shared.native_participant import NativePowerControlSelection

    binding = installed_action[2]
    selection = NativePowerControlSelection(
        participant_address=binding.participant_address,
        controller_address=binding.controller_address,
        pause_action_contract_address="participant.action-contract.foreign",
        resume_action_contract_address="participant.action-contract.request-resume",
        observation_boundary_address=binding.observation_boundary_address,
    )
    with pytest.raises(ValueError):
        candidate(installed_action, selection=selection)


@pytest.mark.parametrize("evidence_known", [True, False])
def test_candidate_passes_public_planning_and_governed_native_admission(installed_action, tmp_path, evidence_known):
    from raes_contracts.errors import ConflictError
    from raes_processor.planner import plan
    from raes_runtime.control_plane_security import (
        ControlPlaneIdentity,
        ControlPlaneRole,
        ParticipantControlSubjectBinding,
    )
    from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration

    from shared.raes.native_control_plane import create_native_control_plane
    from tests.shared.raes.test_native_participant_actions import _control, _CutResolver
    from tests.shared.raes.test_native_participant_crossings import _crossing_evidence, _CrossingOwner

    scenario, model, initial, action, port, _ = installed_action
    built = candidate(installed_action)
    binding = next(item for item in built.bindings if item.verb == initial.verb)
    action = replace(
        action,
        implementation_manifest=binding.implementation_manifest,
        implementation_selection=binding.implementation_selection,
    )
    identity = ControlPlaneIdentity(
        identity="synthetic:organizer",
        target_name=built.target.name,
        roles=frozenset({ControlPlaneRole.OPERATOR}),
        participant_control_subjects=(
            ParticipantControlSubjectBinding(
                binding.participant_address,
                binding.controller_address,
            ),
        ),
    )
    crossing = _CrossingOwner()
    if evidence_known:
        crossing.evidence.update(
            ref
            for support in built.target.manifest.participant_runtime.feature_support
            for ref in support.evidence_refs
        )
    owner = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=built.target,
            scenario=scenario,
            context=project_compiled_participants(model),
            coordinates=binding.coordinates,
            store_root=tmp_path,
            resolver=_CutResolver(),
            crossing_policy_resolver=crossing,
            enforce_final_sink_flow_control=False,
            supervision=OperationSupervisionConfiguration(admission_ms=10000, commit_ms=10000, drain_ms=5000),
        )
    ).owner
    try:
        execution = plan(
            built.model, built.target.manifest, mixed_control_admission=owner.mixed_control_planning_admission()
        )
        assert execution.is_valid, [(item.code, item.message) for item in execution.diagnostics]
        owner.register_planner_produced_plan(execution)
        owner.initialize_participant_episode(
            binding.participant_address, episode_id="episode:fixture", identity=identity
        )
        evidence = _crossing_evidence()
        if not evidence_known:
            with pytest.raises(ConflictError, match="participant crossing conflicts"):
                _control(owner, binding, action, identity, crossing_evidence=evidence)
            assert port.requests == []
            return
        _control(owner, binding, action, identity, crossing_evidence=evidence)
        receipt = owner.admit_participant_action(
            built.model.participant_behaviors[binding.participant_address],
            action,
            identity=identity,
            crossing_evidence=evidence,
        )
        assert owner.get_operation(receipt.operation_id).state.value == "succeeded"
        assert len(port.requests) == 1
        history = owner.snapshot.participant_control_history[binding.participant_address]
        assert history and all(record["schema_version"] == "2.0.0" for record in history)
    finally:
        owner.close()


def test_planning_only_owner_does_not_initialize_or_invoke_a_participant(installed_action):
    from raes_processor.planner import plan

    from shared.raes.native_control_plane import native_control_planner
    from tests.shared.raes.test_native_participant_actions import _CutResolver
    from tests.shared.raes.test_native_participant_crossings import _CrossingOwner

    scenario, model, _, _, port, _ = installed_action
    built = candidate(installed_action)
    with native_control_planner(
        target=built.target,
        scenario=scenario,
        context=project_compiled_participants(model),
        resolver=_CutResolver(),
        crossing_policy_resolver=_CrossingOwner(),
        enforce_final_sink_flow_control=False,
    ) as planner:
        execution = plan(built.model, built.target.manifest, mixed_control_admission=planner.admission)
        assert execution.is_valid
        planner.register(execution)
    assert port.requests == []


def planning_target(installed):
    from shared.native_participant import NativePowerControlSelection
    from shared.raes.native_power_candidate import build_native_power_planning_target

    scenario, model, binding, _, _, _ = installed
    return build_native_power_planning_target(
        scenario=scenario,
        context=project_compiled_participants(model),
        selection=NativePowerControlSelection(
            participant_address=binding.participant_address,
            controller_address=binding.controller_address,
            pause_action_contract_address="participant.action-contract.request-pause",
            resume_action_contract_address="participant.action-contract.request-resume",
            observation_boundary_address=binding.observation_boundary_address,
        ),
        dispatch=_UnusedDispatch(),
    )


def test_prospective_mapping_can_be_planned_before_resources_exist(installed_action):
    from raes_processor.planner import plan

    from shared.raes.native_control_plane import native_control_planner
    from tests.shared.raes.test_native_participant_actions import _CutResolver
    from tests.shared.raes.test_native_participant_crossings import _CrossingOwner

    scenario, model, _, _, _, _ = installed_action
    target = planning_target(installed_action)
    with native_control_planner(
        target=target,
        scenario=scenario,
        context=project_compiled_participants(model),
        resolver=_CutResolver(),
        crossing_policy_resolver=_CrossingOwner(),
        enforce_final_sink_flow_control=False,
    ) as planner:
        execution = plan(model, target.manifest, mixed_control_admission=planner.admission)
        assert execution.is_valid
        planner.register(execution)


def test_planning_runtime_cannot_execute_a_valid_approved_action(admitted, installed_action):
    owner, _, binding, action, identity, port, _ = admitted
    from tests.shared.raes.test_native_participant_actions import _control

    _control(owner, binding, action, identity)
    target = planning_target(installed_action)
    outcome = target.participant_runtime.admit_action(action, owner.snapshot)
    assert not outcome.success
    assert port.requests == []
