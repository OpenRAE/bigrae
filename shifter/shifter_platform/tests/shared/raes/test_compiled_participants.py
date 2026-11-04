"""Generation binding starts from retained public compiler input, not sidecar guesses."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from raes import parse_sdl, parse_sdl_file
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.models import RuntimeModel

_SCENARIO = Path(__file__).parent / "fixtures/launchable/shifter-launch-access.sdl.yaml"


def test_compiled_participants_preserve_resolved_scope():
    from shared.raes.compiled_participants import project_compiled_participants

    model = compile_scenario_runtime_model(parse_sdl_file(_SCENARIO))

    context = project_compiled_participants(model)

    assert context is not None
    assert context.compiler_input_digest.startswith("sha256:")
    assert context.parameters_json == b"{}"
    assert context.reference_payload() == [
        {
            "participant_ref": "participant.behavior.analyst",
            "scope_refs": [],
            "behavior_specification_refs": [],
        }
    ]


def test_private_parameter_values_stay_out_of_reference_projection():
    from shared.raes.compiled_participants import project_compiled_participants

    source = yaml.safe_load(_SCENARIO.read_text())
    source["variables"] = {"note": {"type": "string", "default": "fallback"}}
    parameters = {"note": "synthetic-private-parameter"}
    model = compile_scenario_runtime_model(parse_sdl(yaml.safe_dump(source)), parameters=parameters)

    context = project_compiled_participants(model, parameters=parameters)
    parameters["note"] = "changed-after-compilation"

    assert context is not None
    assert context.parameters_json == b'{"note":"synthetic-private-parameter"}'
    assert "synthetic-private-parameter" not in repr(context)
    assert "synthetic-private-parameter" not in repr(context.reference_payload())


def test_reference_projection_uses_the_retained_compiler_input():
    from shared.raes.compiled_participants import project_compiled_participants

    model = compile_scenario_runtime_model(parse_sdl_file(_SCENARIO))
    original = project_compiled_participants(model)
    altered = deepcopy(model)
    altered.participant_behaviors.clear()

    assert project_compiled_participants(altered) == original


def test_missing_compiler_input_cannot_create_a_binding():
    from shared.raes.compiled_participants import project_compiled_participants

    with pytest.raises(ValueError, match="compiler input"):
        project_compiled_participants(RuntimeModel(scenario_name="synthetic"))


def test_retained_selection_reconstructs_the_same_public_runtime_model():
    from shared.raes.compiled_participants import project_compiled_participants, restore_compiled_model

    source = yaml.safe_load(_SCENARIO.read_text())
    source["variables"] = {"note": {"type": "string", "default": "fallback"}}
    scenario = parse_sdl(yaml.safe_dump(source))
    parameters = {"note": "synthetic-private-parameter"}
    original = compile_scenario_runtime_model(scenario, parameters=parameters)
    context = project_compiled_participants(original, parameters=parameters)

    restored = restore_compiled_model(scenario, context)

    assert restored == original
    assert project_compiled_participants(restored, parameters=parameters) == context


@pytest.mark.parametrize("fault", ["source", "parameters", "digest", "version", "references"])
def test_model_reconstruction_refuses_changed_input_without_private_diagnostics(fault):
    from shared.raes.compiled_participants import project_compiled_participants, restore_compiled_model

    scenario = parse_sdl_file(_SCENARIO)
    context = project_compiled_participants(compile_scenario_runtime_model(scenario))
    assert context is not None
    if fault == "source":
        scenario = scenario.model_copy(update={"name": "synthetic-private-changed-name"})
    elif fault == "parameters":
        context = replace(context, parameters_json=b'{"undeclared":"synthetic-private-parameter"}')
    elif fault == "digest":
        context = replace(context, compiler_input_digest="sha256:" + "d" * 64)
    elif fault == "version":
        context = replace(context, raes_version="0.0.0")
    else:
        context = replace(context, participants=())
    with pytest.raises(ValueError, match="Retained compiler input changed") as failure:
        restore_compiled_model(scenario, context)
    assert "synthetic-private" not in str(failure.value)
    assert failure.value.__suppress_context__
