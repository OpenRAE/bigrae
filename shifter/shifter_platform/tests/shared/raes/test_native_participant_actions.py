"""Installed native actions require real released proposal and approval history."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from raes import parse_sdl, parse_sdl_file
from raes_contracts.canonical import canonical_json_digest
from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
from raes_contracts.contracts.participant_manifests import (
    ParticipantImplementationManifestModel,
    ParticipantImplementationSelectionModel,
)
from raes_contracts.runtime_state import RuntimeSnapshot
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.models.participant_action_arguments import resolve_participant_action_arguments
from raes_runtime.control_plane_security import (
    ControlPlaneIdentity,
    ControlPlaneRole,
    ParticipantControlSubjectBinding,
)
from raes_runtime.participant_control_intents import ParticipantApprovalControlIntent, ParticipantProposalControlIntent
from raes_runtime.participant_control_runtime import ParticipantControlLiveCut

from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import (
    NativeControlPlaneConfiguration,
    NativeRuntimeCoordinates,
    create_native_control_plane,
)

from .test_native_control_plane import _target

_PARTICIPANT = "participant.behavior.analyst"
_OBSERVATION = "participant.observation-boundary.native-status"
_FIXTURE = Path(__file__).parent / "fixtures/control/participant-power-admission.sdl.yaml"


class _ReservationPort:
    def __init__(self):
        self.requests = []
        self.operation_id = uuid4()
        self.failure = None

    def reserve(self, action):
        if self.failure:
            raise self.failure
        self.requests.append(action)
        return self.operation_id


class _CutResolver:
    """Explicit fixture grants; production supplies current native authorization."""

    revoked = False

    def resolve_cut(self, policy, intent, snapshot):
        return ParticipantControlLiveCut(
            request_ref=intent.client_correlation_id if intent else "fixture:initial",
            effective_order=len(snapshot.participant_control_history.get(_PARTICIPANT, ())) + (1 if intent else 0),
            active_authority_basis_refs=["entities.operators"],
            authorized_scope_refs=["provision.node.web"],
            evidence_refs=["fixture:authority"],
        )

    def resolve_action_cut(self, policy, request, snapshot):
        return ParticipantControlLiveCut(
            request_ref=request.action_instance_id,
            effective_order=len(snapshot.participant_control_history.get(_PARTICIPANT, ())) + 1,
            active_authority_basis_refs=[] if self.revoked else ["entities.operators"],
            authorized_scope_refs=["provision.node.web"],
            evidence_refs=["fixture:action-authority"],
        )


def _implementation():
    manifest = ParticipantImplementationManifestModel.model_validate(
        {
            "schema_version": "participant-implementation-manifest/v1",
            "identity": {"name": "synthetic-native-supervision", "version": "1.0.0"},
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
    selection = ParticipantImplementationSelectionModel.model_validate(
        {
            "participant_address": _PARTICIPANT,
            "implementation_identity": manifest.identity.model_dump(mode="json"),
            "manifest_ref": "fixture:installed-manifest",
            "manifest_digest": canonical_json_digest(manifest.model_dump(mode="json")),
            "selected_decision_surface_mode": "human-supervised",
            "participant_contract_versions": ["participant-episode-state-envelope-v1"],
            "exposure_policy": {
                "policy_id": "fixture:references",
                "exposure_policy_kinds": ["observation-stream"],
                "visibility_scope_refs": ["provision.node.web"],
            },
        }
    )
    return manifest, selection


@pytest.fixture(params=["pause", "resume"])
def installed_action(request):
    from shared.raes.native_participant_actions import NativePowerActionBinding, NativePowerParticipantRuntime

    scenario = parse_sdl_file(_FIXTURE)
    model = compile_scenario_runtime_model(scenario)
    manifest, selection = _implementation()
    binding = NativePowerActionBinding(
        coordinates=NativeRuntimeCoordinates(uuid4(), uuid4(), uuid4()),
        participant_address=_PARTICIPANT,
        controller_address="participant.behavior.organizer",
        action_contract_address=f"participant.action-contract.request-{request.param}",
        observation_boundary_address=_OBSERVATION,
        target_addresses=("provision.node.web",),
        verb=request.param,
        implementation_manifest=manifest,
        implementation_selection=selection,
        compiler_input_digest=canonical_json_digest(model.realization_instance.model_dump(mode="json")),
    )
    port = _ReservationPort()
    port.resolver = _CutResolver()
    runtime = NativePowerParticipantRuntime(model=model, bindings=(binding,), port=port)
    contract = model.action_contracts[binding.action_contract_address]
    action = ParticipantActionAdmissionRequest(
        participant_address=_PARTICIPANT,
        action_contract_address=contract.address,
        observation_boundary_address=_OBSERVATION,
        action_instance_id=str(uuid4()),
        implementation_manifest=manifest,
        implementation_selection=selection,
        validated_selection=resolve_participant_action_arguments(
            contract,
            action_contract_address=contract.address,
            argument_shape_ref=contract.argument_shape_ref,
            proposal_ref=str(uuid4()),
            proposed_arguments={},
        ),
        target_addresses=binding.target_addresses,
    )
    return scenario, model, binding, action, port, runtime


@pytest.fixture
def admitted(tmp_path, installed_action):
    scenario, model, binding, action, port, runtime = installed_action
    target = replace(_target(scenario), participant_runtime=runtime)
    plane = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=target,
            scenario=scenario,
            context=project_compiled_participants(model),
            store_root=tmp_path,
            coordinates=binding.coordinates,
            resolver=port.resolver,
        )
    ).owner
    try:
        identity = ControlPlaneIdentity(
            identity="fixture:organizer",
            roles=frozenset({ControlPlaneRole.OPERATOR}),
            target_name=plane.target_name,
            participant_control_subjects=(
                ParticipantControlSubjectBinding(_PARTICIPANT, "participant.behavior.organizer"),
            ),
        )
        plane.initialize_participant_episode(_PARTICIPANT, episode_id="episode:fixture", identity=identity)
        yield plane, model.participant_behaviors[_PARTICIPANT], binding, action, identity, port, runtime
    finally:
        plane.close()


def _control(plane, binding, action, identity, *, approve=True, digest=None, crossing_evidence=None):
    from shared.raes.native_participant_actions import native_power_action_commitment

    common = {
        "episode_id": "episode:fixture",
        "policy_revision": "1.0.0",
        "provenance_refs": ["fixture:source"],
        "evidence_refs": ["fixture:authority"],
        "object_marking_refs": ["fixture:synthetic"],
        "limitation_refs": ["fixture:bounded"],
    }
    application = {
        "semantics": "mixed-control-policy-occurrence/rev1",
        "policy_ref": "participant.behavior-specification.controlled.mixed-control-policy",
        "prior_state_ref": "participant.behavior-specification.controlled.controller-state.active",
    }
    plane.record_participant_control(
        _PARTICIPANT,
        ParticipantProposalControlIntent(
            **common,
            declaration_ref="participant.behavior-specification.controlled.permitted-transition.propose",
            client_correlation_id="fixture:proposal",
            expected_state_revision=0,
            proposal_id=action.validated_selection.proposal_ref,
            proposal_revision=1,
            action_contract_ref=action.action_contract_address,
            payload_digest=digest or native_power_action_commitment(binding, action, "episode:fixture"),
            application={**application, "expected_history_head": 0, "effective_order": 1},
        ),
        identity=identity,
        crossing_evidence=crossing_evidence,
    )
    if approve:
        plane.record_participant_control(
            _PARTICIPANT,
            ParticipantApprovalControlIntent(
                **common,
                declaration_ref="participant.behavior-specification.controlled.permitted-transition.approve",
                client_correlation_id="fixture:approval",
                expected_state_revision=1,
                proposal_ref=action.validated_selection.proposal_ref,
                proposal_revision=1,
                decision_ref=str(uuid4()),
                decision_revision=1,
                application={**application, "expected_history_head": 1, "effective_order": 2},
            ),
            identity=identity,
            crossing_evidence=crossing_evidence,
        )


def test_approved_action_reserves_native_work_and_records_only_an_admission(admitted):
    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    receipt = plane.admit_participant_action(behavior, action, identity=identity, idempotency_key="fixture:action")
    approval = list(plane.snapshot.participant_control_history[binding.participant_address])[-1]["occurrence"]
    assert port.requests[0].approval_ref == approval["decision_ref"]
    status = plane.get_operation(receipt.operation_id)
    assert status.state.value == "succeeded", [(d.code, d.message) for d in status.diagnostics]
    assert len(port.requests) == 1
    reserved = port.requests[0]
    assert reserved.verb == binding.verb
    assert reserved.coordinates == binding.coordinates
    assert reserved.action_id == action.action_instance_id
    history = list(plane.snapshot.participant_behavior_history[_PARTICIPANT])
    assert action.action_instance_id in str(history)
    assert str(port.operation_id) not in str(history)
    assert "accepted" in str(history)
    assert "provider" not in str(history)
    assert binding.compiler_input_digest not in str(history)
    assert binding.compiler_input_digest not in repr(reserved)
    result = next(event["action_result"] for event in history if "action_result" in event)
    assert result["status"] == "accepted"
    assert not result.get("effects")
    repeated = plane.admit_participant_action(behavior, action, identity=identity, idempotency_key="fixture:action")
    assert repeated.operation_id == receipt.operation_id
    assert len(port.requests) == 1


@pytest.mark.parametrize(
    "condition", ["no-proposal", "no-approval", "different-meaning", "missing-selection", "terminal"]
)
def test_incomplete_or_changed_approval_never_reserves_native_work(admitted, condition):
    plane, behavior, binding, action, identity, port, _ = admitted
    if condition != "no-proposal":
        _control(
            plane,
            binding,
            action,
            identity,
            approve=condition != "no-approval",
            digest="sha256:" + "0" * 64 if condition == "different-meaning" else None,
        )
    if condition == "missing-selection":
        action = replace(action, validated_selection=None)
    if condition == "terminal":
        action = replace(action, requires_terminal_outcome=True)
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert port.requests == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_addresses", ("provision.node.other",)),
        ("observation_boundary_address", "participant.observation-boundary.other"),
        ("post_state_digest", "sha256:" + "0" * 64),
    ],
)
def test_installed_action_cannot_be_retargeted(admitted, field, value):
    plane, _, binding, action, identity, port, runtime = admitted
    _control(plane, binding, action, identity)
    outcome = runtime.admit_action(replace(action, **{field: value}), plane.snapshot)
    assert not outcome.success
    assert port.requests == []


def test_raw_native_fault_is_not_portable(admitted):
    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    port.failure = RuntimeError("provider credential and private response")
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    status = plane.get_operation(receipt.operation_id)
    assert status.state.value == "failed"
    assert "provider credential" not in str(status)
    assert "private response" not in str(plane.snapshot)


def test_reference_only_or_empty_snapshot_cannot_reach_native_port(admitted):
    _, _, _, action, _, port, runtime = admitted
    assert not runtime.admit_action(action, RuntimeSnapshot()).success
    assert port.requests == []


def test_approval_cannot_be_reused_for_another_action_occurrence(admitted):
    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    changed = replace(action, action_instance_id=str(uuid4()))
    receipt = plane.admit_participant_action(behavior, changed, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert port.requests == []


def test_revoked_live_authority_after_approval_prevents_reservation(admitted):
    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    port.resolver.revoked = True
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert port.requests == []


def test_changed_implementation_selection_is_not_an_installed_binding(admitted):
    plane, _, binding, action, identity, port, runtime = admitted
    _control(plane, binding, action, identity)
    selection = action.implementation_selection.model_copy(update={"manifest_ref": "fixture:foreign-installation"})
    outcome = runtime.admit_action(replace(action, implementation_selection=selection), plane.snapshot)
    assert not outcome.success
    assert port.requests == []


def test_one_runtime_cannot_join_bindings_from_different_runs(installed_action):
    from shared.raes.native_participant_actions import NativePowerParticipantRuntime

    _, model, binding, _, port, _ = installed_action
    alternate_contract = "request-resume" if binding.verb == "pause" else "request-pause"
    changed = replace(
        binding,
        coordinates=replace(binding.coordinates, run_id=uuid4()),
        action_contract_address=f"participant.action-contract.{alternate_contract}",
        verb="resume" if binding.verb == "pause" else "pause",
    )
    with pytest.raises(ValueError, match="Installed native action binding"):
        NativePowerParticipantRuntime(model=model, bindings=(binding, changed), port=port)


def test_exhausted_native_history_budget_withholds_work(admitted, monkeypatch):
    from shared.raes import native_participant_actions

    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    monkeypatch.setattr(native_participant_actions, "MAX_NATIVE_CONTROL_RECORDS", 1)
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert port.requests == []


def test_cancelled_approval_cannot_reach_the_native_reservation_port(admitted):
    plane, behavior, binding, action, identity, port, _ = admitted
    _control(plane, binding, action, identity)
    _cancel_approval(plane, identity)
    receipt = plane.admit_participant_action(behavior, action, identity=identity)
    assert plane.get_operation(receipt.operation_id).state.value == "failed"
    assert port.requests == []


def _cancel_approval(plane, identity, *, crossing_evidence=None):
    from raes_runtime.participant_control_intents import ParticipantCancellationControlIntent

    approval = list(plane.snapshot.participant_control_history[_PARTICIPANT])[-1]["occurrence"]
    plane.record_participant_control(
        _PARTICIPANT,
        ParticipantCancellationControlIntent(
            episode_id="episode:fixture",
            policy_revision="1.0.0",
            expected_state_revision=2,
            declaration_ref="participant.behavior-specification.controlled.permitted-transition.cancel",
            client_correlation_id="fixture:cancel",
            provenance_refs=["fixture:source"],
            evidence_refs=["fixture:authority"],
            object_marking_refs=["fixture:synthetic"],
            limitation_refs=["fixture:bounded"],
            target_kind="decision",
            target_ref=approval["decision_ref"],
            target_revision=1,
            application={
                "semantics": "mixed-control-policy-occurrence/rev1",
                "policy_ref": "participant.behavior-specification.controlled.mixed-control-policy",
                "prior_state_ref": "participant.behavior-specification.controlled.controller-state.active",
                "expected_history_head": 2,
                "effective_order": 3,
            },
        ),
        identity=identity,
        crossing_evidence=crossing_evidence,
    )
    occurrence = list(plane.snapshot.participant_control_history[_PARTICIPANT])[-1]["occurrence"]
    assert occurrence["disposition"] == "accepted", occurrence.get("reason_code")


def test_portable_proposal_digest_does_not_reveal_private_compiler_selection(installed_action):
    from shared.raes.native_participant_actions import native_power_action_commitment

    _, _, binding, action, _, _ = installed_action
    changed = replace(binding, compiler_input_digest="sha256:" + "0" * 64)
    assert native_power_action_commitment(binding, action, "episode:fixture") == native_power_action_commitment(
        changed,
        action,
        "episode:fixture",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("realization_profile", "foreign-native-profile/v1"),
        ("semantic_version", "2.0.0"),
        (
            "effects",
            [
                {
                    "effect_id": "changed",
                    "effect_class": "intended_effect",
                    "description": "Changed meaning",
                    "target_refs": ["nodes.web"],
                }
            ],
        ),
    ],
)
def test_native_mapping_refuses_an_uninstalled_action_semantics(installed_action, field, value):
    from shared.raes.native_participant_actions import NativePowerParticipantRuntime

    _, _, binding, _, port, _ = installed_action
    authored = yaml.safe_load(_FIXTURE.read_text())
    authored["action_contracts"][f"request-{binding.verb}"][field] = value
    model = compile_scenario_runtime_model(parse_sdl(yaml.safe_dump(authored)))
    changed = replace(
        binding, compiler_input_digest=canonical_json_digest(model.realization_instance.model_dump(mode="json"))
    )
    with pytest.raises(ValueError, match="Installed native action binding is unavailable"):
        NativePowerParticipantRuntime(model=model, bindings=(changed,), port=port)
