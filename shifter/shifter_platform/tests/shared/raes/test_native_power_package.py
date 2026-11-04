"""Selected native control planning preserves the incumbent package safeguards."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from shared.native_participant import NativePowerControlSelection
from shared.raes.package_loader import launch_raes_package
from tests.shared.raes.test_package_loader import _RecordingPort

_SOURCE = Path(__file__).parent / "fixtures/control/participant-power-admission.sdl.yaml"


@pytest.fixture
def source(tmp_path):
    authored = yaml.safe_load(_SOURCE.read_text())
    # The incumbent native access profile is participant-invariant. This
    # qualification fixture explicitly grants the same guest access to both
    # declared roles; a control mapping never supplies a missing guest grant.
    for field in ("starting_accounts", "interactive_access"):
        authored["agents"]["organizer"][field] = deepcopy(authored["agents"]["analyst"][field])
    path = tmp_path / "controlled.sdl.yaml"
    path.write_text(yaml.safe_dump(authored))
    return path


def selection():
    return NativePowerControlSelection(
        participant_address="participant.behavior.analyst",
        controller_address="participant.behavior.organizer",
        pause_action_contract_address="participant.action-contract.request-pause",
        resume_action_contract_address="participant.action-contract.request-resume",
        observation_boundary_address="participant.observation-boundary.native-status",
    )


def test_control_declarations_alone_do_not_activate_native_planning(source):
    port = _RecordingPort()
    result = launch_raes_package(scenario_path=source, port=port)
    assert not result.accepted
    assert port.plans == []


def test_installed_logical_selection_plans_and_dispatches_the_retained_source(source):
    port = _RecordingPort()
    result = launch_raes_package(scenario_path=source, port=port, native_control_selection=selection())
    assert result.accepted, result.diagnostics
    assert len(port.plans) == 1
    assert port.contexts[0].participants


def test_invalid_installed_selection_never_falls_back_or_dispatches(source):
    port = _RecordingPort()
    invalid = replace(selection(), pause_action_contract_address="participant.action-contract.foreign")
    result = launch_raes_package(scenario_path=source, port=port, native_control_selection=invalid)
    assert not result.accepted
    assert port.plans == []
    assert result.diagnostics == ("shifter-provisioner.participant-control-unavailable",)


@pytest.mark.parametrize("available", [False, True])
def test_native_planning_still_requires_actual_artifact_admission(tmp_path, source, available):
    from shared.raes.artifact_inventory import build_artifact_supply
    from tests.shared.raes.test_prepared_inventory import inventory_fixture

    requirement, owned = inventory_fixture()
    authored = yaml.safe_load(source.read_text())
    authored["nodes"]["web"]["source"]["artifact_requirement"] = requirement.model_dump(mode="json")
    path = tmp_path / "controlled.sdl.yaml"
    path.write_text(yaml.safe_dump(authored))
    observed = []

    def supply(requirements):
        observed.extend(requirements)
        return build_artifact_supply(requirements, [owned] if available else [])

    port = _RecordingPort()
    result = launch_raes_package(
        scenario_path=path,
        port=port,
        native_control_selection=selection(),
        artifact_supply_provider=supply,
    )
    assert result.accepted is available, result.diagnostics
    assert len(port.plans) == int(available)
    assert observed == ["provision.node.web"]


def test_private_native_parameters_remain_outside_the_serialized_plan(tmp_path, source):
    authored = yaml.safe_load(source.read_text())
    authored["variables"] = {"private_note": {"type": "string"}}
    path = tmp_path / "controlled.sdl.yaml"
    path.write_text(yaml.safe_dump(authored))
    port = _RecordingPort()
    result = launch_raes_package(
        scenario_path=path,
        port=port,
        native_control_selection=selection(),
        parameters={"private_note": "synthetic-private-control-parameter"},
    )
    assert result.accepted, result.diagnostics
    assert "synthetic-private-control-parameter" not in json.dumps(port.plans)
    assert "synthetic-private-control-parameter" not in repr(port.contexts[0])
    assert "synthetic-private-control-parameter" in port.contexts[0].parameters_json.decode()


def test_control_selection_cannot_relax_the_native_guest_access_envelope():
    port = _RecordingPort()
    result = launch_raes_package(scenario_path=_SOURCE, port=port, native_control_selection=selection())
    assert not result.accepted
    assert result.diagnostics[0].startswith("shifter-provisioner.participant-access-unrealizable:")
    assert port.plans == []
