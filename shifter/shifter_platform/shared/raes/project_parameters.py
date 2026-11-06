"""Native parameter declarations supplied by a registered range project."""

from collections.abc import Mapping
from pathlib import Path

from raes.scenarios import load_scenario

PROJECT_PARAMETERS = frozenset({"project_id", "project_number"})


def required_project_parameters(scenario_path: Path) -> frozenset[str]:
    """Only registered-project facts may defer a template's conformance check."""
    scenario = load_scenario(scenario_path)
    missing = frozenset(
        name for name, variable in scenario.variables.items() if variable.required and variable.default is None
    )
    if missing - PROJECT_PARAMETERS:
        raise ValueError("The pack requires unsupported runtime parameters")
    if any(scenario.variables[name].type != "string" for name in missing):
        raise ValueError("Registered project parameters must be strings")
    return missing


def select_project_parameters(scenario_path: Path, facts: Mapping[str, str]) -> dict[str, object]:
    """Pass only declared native parameters; never rewrite the source document."""
    scenario = load_scenario(scenario_path)
    return {name: value for name, value in facts.items() if name in PROJECT_PARAMETERS and name in scenario.variables}
