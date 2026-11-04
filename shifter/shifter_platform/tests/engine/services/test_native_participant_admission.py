"""Released durable admission reaches actual native authority and held work.

The footprint is synthetic and the SDK cut resolver has fixture grants.
These tests establish neither deployed conformance nor a cloud power outcome.
"""

from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from raes import parse_sdl_file
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.planner import plan
from raes_runtime.control_plane_security import ControlPlaneIdentity, ControlPlaneRole, ParticipantControlSubjectBinding
from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration

from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import (
    NativeControlPlaneConfiguration,
    NativeRuntimeCoordinates,
    create_native_control_plane,
)
from shared.raes.native_participant_actions import (
    NativePowerActionBinding,
    NativePowerParticipantRuntime,
    native_participant_control_cut,
)
from tests.engine.services.test_native_compiler_context import create_compiled_native_case, tenant
from tests.engine.services.test_native_participant_reservation import _native_action_case
from tests.shared.raes.test_native_control_plane import _target
from tests.shared.raes.test_native_participant_actions import _cancel_approval, _control, _CutResolver, _implementation
from tests.shared.raes.test_native_participant_crossings import _crossing_evidence, _CrossingOwner, _governed_target

__all__ = ["tenant"]
pytestmark = pytest.mark.django_db(transaction=True)
_PARTICIPANT = "participant.behavior.analyst"
_CONTROLLER = "participant.behavior.organizer"
# These tests measure protocol/authority behavior, not host fsync latency.
# Production uses the SDK defaults unless installation policy supplies bounds.
_TEST_IO = OperationSupervisionConfiguration(admission_ms=10000, commit_ms=10000, drain_ms=5000)


@pytest.fixture
def controlled_range(tenant, settings, tmp_path):
    source = Path(__file__).parents[2] / "shared/raes/fixtures/control/participant-power-admission.sdl.yaml"
    scenario = parse_sdl_file(source)

    def build(scenario, parameters):
        model = compile_scenario_runtime_model(scenario, parameters=parameters)
        target = _governed_target(scenario, _target(scenario).participant_runtime)
        owner = create_native_control_plane(
            NativeControlPlaneConfiguration(
                target=target,
                scenario=scenario,
                context=project_compiled_participants(model, parameters=parameters),
                store_root=tmp_path / "planning",
                coordinates=NativeRuntimeCoordinates(uuid4(), uuid4(), uuid4()),
                resolver=_CutResolver(),
                supervision=_TEST_IO,
                crossing_policy_resolver=_CrossingOwner(),
                enforce_final_sink_flow_control=False,
            )
        ).owner
        try:
            execution = plan(model, target.manifest, mixed_control_admission=owner.mixed_control_planning_admission())
            assert execution.is_valid, [(diagnostic.code, diagnostic.message) for diagnostic in execution.diagnostics]
            owner.register_planner_produced_plan(execution)
            return execution
        finally:
            owner.close()

    return create_compiled_native_case(tenant, settings, scenario, {}, build)


class _EnginePort:
    def __init__(self, case):
        self.case = case

    def reserve(self, action):
        from django.db import connections

        from engine.services._native_participant_power import reserve_native_participant_power

        try:
            return reserve_native_participant_power(self.case.credential, self.case.request_id, action)
        finally:
            # The SDK invokes this fixture on its backend executor thread.
            connections.close_all()


@pytest.mark.parametrize("verb", ["pause", "resume"])
@pytest.mark.parametrize("phase", ["current", "revoked", "cancelled"])
def test_released_admission_reserves_only_currently_authorized_native_work(controlled_range, tmp_path, verb, phase):
    from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
    from raes_processor.models.participant_action_arguments import resolve_participant_action_arguments

    from engine.models import ParticipantPowerReservation
    from engine.services._native_participant_dispatch import release_native_participant_power
    from engine.services._native_participant_power import record_native_participant_admission

    case, native = _native_action_case(controlled_range, verb)
    model = compile_scenario_runtime_model(case.scenario)
    manifest, selection = _implementation()
    binding = NativePowerActionBinding(
        coordinates=native.coordinates,
        participant_address=_PARTICIPANT,
        controller_address=_CONTROLLER,
        action_contract_address=native.action_contract_address,
        observation_boundary_address=native.observation_boundary_address,
        target_addresses=native.target_addresses,
        verb=verb,
        implementation_manifest=manifest,
        implementation_selection=selection,
        compiler_input_digest=case.context.compiler_input_digest,
    )
    target = replace(
        _target(case.scenario),
        participant_runtime=NativePowerParticipantRuntime(
            model=model,
            bindings=(binding,),
            port=_EnginePort(case),
        ),
    )
    target = _governed_target(case.scenario, target.participant_runtime)
    crossing = _CrossingOwner()
    evidence = _crossing_evidence()
    owner = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=target,
            scenario=case.scenario,
            context=case.context,
            store_root=tmp_path / "native",
            coordinates=native.coordinates,
            resolver=_CutResolver(),
            supervision=_TEST_IO,
            crossing_policy_resolver=crossing,
            enforce_final_sink_flow_control=False,
        )
    ).owner
    identity = ControlPlaneIdentity(
        identity=f"principal:{case.credential.principal.uuid}",
        target_name=owner.target_name,
        roles=frozenset({ControlPlaneRole.OPERATOR}),
        participant_control_subjects=(ParticipantControlSubjectBinding(_PARTICIPANT, _CONTROLLER),),
    )
    contract = model.action_contracts[binding.action_contract_address]
    request = ParticipantActionAdmissionRequest(
        participant_address=_PARTICIPANT,
        action_contract_address=contract.address,
        observation_boundary_address=binding.observation_boundary_address,
        action_instance_id=native.action_id,
        implementation_manifest=manifest,
        implementation_selection=selection,
        target_addresses=binding.target_addresses,
        validated_selection=resolve_participant_action_arguments(
            contract,
            action_contract_address=contract.address,
            argument_shape_ref=contract.argument_shape_ref,
            proposal_ref=native.proposal_ref,
            proposed_arguments={},
        ),
    )
    try:
        owner.initialize_participant_episode(_PARTICIPANT, episode_id="episode:fixture", identity=identity)
        _control(owner, binding, request, identity, crossing_evidence=evidence)
        if phase == "revoked":
            case.actor.policy_principals.clear()
        receipt = owner.admit_participant_action(
            model.participant_behaviors[_PARTICIPANT], request, identity=identity, crossing_evidence=evidence
        )
        assert owner.snapshot.participant_crossing_history[_PARTICIPANT]
        assert not owner.snapshot.participant_control_evaluation_history
        status = owner.get_operation(receipt.operation_id)
        if phase == "revoked":
            assert status.state.value == "failed"
            assert not ParticipantPowerReservation.objects.exists()
        else:
            assert status.state.value == "succeeded", [
                (diagnostic.code, diagnostic.message) for diagnostic in status.diagnostics
            ]
            reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get()
            assert reservation.action_id == UUID(native.action_id)
            assert reservation.run_id == native.coordinates.run_id
            assert reservation.launch_intent.status == "HELD"
            assert reservation.portable_operation_uuid is None
            assert reservation.launch_intent.initiating_principal_uuid == case.credential.principal.uuid
            if phase == "cancelled":
                _cancel_approval(owner, identity, crossing_evidence=evidence)
            cut = native_participant_control_cut(owner.snapshot, _PARTICIPANT, "episode:fixture")
            if phase == "cancelled":
                assert owner.get_operation(receipt.operation_id).state.value == "succeeded"
                assert reservation.control_cut_digest != cut
                with pytest.raises(ValueError, match="Native participant operation unavailable"):
                    record_native_participant_admission(
                        case.credential,
                        UUID(native.action_id),
                        portable_operation_uuid=UUID(receipt.operation_id),
                        control_cut_digest=cut,
                    )
            else:
                assert reservation.control_cut_digest == cut
                record_native_participant_admission(
                    case.credential,
                    UUID(native.action_id),
                    portable_operation_uuid=UUID(receipt.operation_id),
                    control_cut_digest=cut,
                )
                assert (
                    release_native_participant_power(
                        case.credential,
                        UUID(native.action_id),
                        portable_operation_uuid=UUID(receipt.operation_id),
                        control_cut_digest=cut,
                    )
                    == reservation.launch_intent.operation_id
                )
            reservation.refresh_from_db()
            assert reservation.portable_operation_uuid == (None if phase == "cancelled" else UUID(receipt.operation_id))
            reservation.launch_intent.refresh_from_db()
            assert reservation.launch_intent.status == ("HELD" if phase == "cancelled" else "PENDING")
    finally:
        owner.close()
