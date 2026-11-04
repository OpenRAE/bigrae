"""Plan selected native control through the public owner and artifact boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from raes_contracts.planning import PlanScope
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.planner import plan

from shared.native_participant import NativePowerConfigurationEvidence, NativePowerControlSelection
from shared.raes.artifact_planning import ArtifactSupplyProvider, prepare_compiled_artifact_target
from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import native_control_planner
from shared.raes.native_power_candidate import build_native_power_planning_target, native_power_implementation_digest

if TYPE_CHECKING:
    from raes.scenarios import Scenario
    from raes_processor.models import ExecutionPlan
    from raes_runtime.registry import RuntimeTarget

    from shared.raes.compiled_participants import CompiledParticipantContext
    from shared.raes.dispatch_port import ShifterProvisioningDispatchPort
    from shared.raes.power_input import NativePowerInput


class _PlanningAuthority:
    """Compilation has no live participant authority and cannot initialize a run."""

    def resolve_cut(self, policy: object, intent: object, snapshot: object) -> NoReturn:
        raise ValueError("Planning cannot authorize participant control")

    def resolve_action_cut(self, policy: object, request: object, snapshot: object) -> NoReturn:
        raise ValueError("Planning cannot authorize participant action")

    def resolve(self, intent: object, snapshot: object) -> NoReturn:
        raise ValueError("Planning cannot authorize a participant crossing")

    def validation_context(self, snapshot: object, participant_address: str) -> NoReturn:
        raise ValueError("Planning has no participant crossing evidence")


def native_power_configuration_evidence() -> NativePowerConfigurationEvidence:
    """Read fixed installed contract identities without planning or accessing private input."""
    return NativePowerConfigurationEvidence(version("raes"), native_power_implementation_digest())


def plan_native_power_with_artifact_supply(
    *,
    scenario: Scenario,
    port: ShifterProvisioningDispatchPort,
    selection: NativePowerControlSelection,
    parameters: Mapping[str, object] | None = None,
    supply_provider: ArtifactSupplyProvider | None = None,
) -> tuple[ExecutionPlan, RuntimeTarget]:
    """Retain exact compiler context and all artifact gates before native dispatch."""
    if not isinstance(selection, NativePowerControlSelection):
        raise ValueError("Installed native control selection unavailable")
    model = compile_scenario_runtime_model(scenario, parameters=parameters)
    context = project_compiled_participants(model, parameters=parameters)
    if context is None:
        raise ValueError("Native control compiler context unavailable")
    target = build_native_power_planning_target(scenario=scenario, context=context, selection=selection, dispatch=port)
    target, availability = prepare_compiled_artifact_target(model, target, supply_provider=supply_provider)
    with native_control_planner(
        target=target,
        scenario=scenario,
        context=context,
        resolver=_PlanningAuthority(),
        crossing_policy_resolver=_PlanningAuthority(),
        enforce_final_sink_flow_control=False,
    ) as planner:
        execution = plan(
            model,
            target.manifest,
            scope=PlanScope(target_name=target.name),
            artifact_availability=availability,
            mixed_control_admission=planner.admission,
        )
        if execution.is_valid:
            planner.register(execution)
    return execution, target


def validate_native_power_configuration(
    scenario_path: Path, selection: NativePowerControlSelection
) -> NativePowerConfigurationEvidence:
    """Validate source structure for this mapping; do not claim runtime conformance."""
    from raes.scenarios import load_scenario

    from shared.raes.pack_conformance import ContractValidationPort, validate_compiled_pack_structure

    execution, _ = plan_native_power_with_artifact_supply(
        scenario=load_scenario(scenario_path),
        port=ContractValidationPort("native-control-source-check"),
        selection=selection,
    )
    validate_compiled_pack_structure(execution)
    context = project_compiled_participants(execution.model)
    if context is None:
        raise ValueError("Native control compiler context unavailable")
    return NativePowerConfigurationEvidence(context.raes_version, native_power_implementation_digest())


def validate_bound_native_power_source(
    scenario_path: Path,
    *,
    context: CompiledParticipantContext,
    power: NativePowerInput,
    selection: NativePowerControlSelection,
) -> NativePowerConfigurationEvidence:
    """Qualify exact retained compilation against current immutable installed source."""
    from raes.scenarios import load_scenario

    from shared.raes.native_power_candidate import validate_bound_native_power_configuration

    validate_bound_native_power_configuration(
        scenario=load_scenario(scenario_path), context=context, power=power, selection=selection
    )
    return NativePowerConfigurationEvidence(context.raes_version, native_power_implementation_digest())
