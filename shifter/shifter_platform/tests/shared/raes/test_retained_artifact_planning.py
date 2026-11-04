"""A recovered controller reuses original admission facts, never today's registry."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from raes.scenarios import load_scenario
from raes_runtime import RuntimeManager

from shared.raes.artifact_inventory import build_artifact_supply
from shared.raes.compiled_participants import restore_compiled_model
from shared.raes.package_loader import launch_raes_package
from shared.raes.runtime_target import create_shifter_backend_target
from tests.shared.raes.test_package_loader import _RecordingPort
from tests.shared.raes.test_prepared_inventory import inventory_fixture


@pytest.fixture
def retained(tmp_path):
    requirement, owned = inventory_fixture()
    source = Path(__file__).parent / "fixtures/launchable/shifter-launch-access.sdl.yaml"
    raw = yaml.safe_load(source.read_text())
    raw["nodes"]["web"]["source"]["artifact_requirement"] = requirement.model_dump(mode="json")
    path = tmp_path / "synthetic-retained-artifacts.sdl.yaml"
    path.write_text(yaml.safe_dump(raw))
    port = _RecordingPort()
    result = launch_raes_package(
        scenario_path=path,
        port=port,
        artifact_supply_provider=lambda requirements: build_artifact_supply(requirements, [owned]),
    )
    assert result.accepted, result.diagnostics
    return load_scenario(path), port.contexts[0], owned


def test_retained_public_facts_allow_planning_without_any_registry(retained):
    from shared.raes.artifact_planning import restore_artifact_planning_target

    scenario, context, owned = retained
    assert context.artifact_planning_json
    model = restore_compiled_model(scenario, context)
    target = create_shifter_backend_target(port=_RecordingPort(), scenario=scenario)
    target, facts = restore_artifact_planning_target(model, target, context=context)
    execution = RuntimeManager(target).plan(scenario, artifact_availability=facts)
    assert execution.is_valid, [item.code for item in execution.diagnostics]
    assert facts.requirements[0].available_artifact_digests == [owned.digest]
    assert "artifact_planning_json" not in repr(context)
    assert all("artifact_planning" not in entry for entry in context.reference_payload())


@pytest.mark.parametrize("fault", ["missing", "compiler", "version", "address"])
def test_missing_or_foreign_retained_facts_never_requalify_the_controller(retained, fault):
    from shared.raes.artifact_planning import restore_artifact_planning_target

    scenario, context, _ = retained
    payload = json.loads(context.artifact_planning_json)
    if fault == "compiler":
        payload["compiler_input_digest"] = "sha256:" + "f" * 64
    elif fault == "version":
        payload["raes_version"] = "synthetic-unsupported-release"
    elif fault == "address":
        payload["availability"]["requirements"][0]["address"] = "provision.node.foreign"
    changed = replace(context, artifact_planning_json=b"" if fault == "missing" else json.dumps(payload).encode())
    model = restore_compiled_model(scenario, changed)
    target = create_shifter_backend_target(port=_RecordingPort(), scenario=scenario)
    with pytest.raises(ValueError, match="Retained artifact planning input unavailable"):
        restore_artifact_planning_target(model, target, context=changed)
