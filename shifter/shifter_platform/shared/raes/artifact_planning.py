"""Join native admission to the public planner's compiled artifact availability seam."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict
from raes.artifact_requirements import ArtifactRequirement
from raes.scenario import ExpandedScenario, InstantiatedScenario, Scenario
from raes_contracts.artifact_requirements import ArtifactAvailabilityContext, ArtifactRequirementAvailability
from raes_contracts.contracts import ArtifactMechanismCapability
from raes_processor.compiler import compile_scenario_runtime_model
from raes_processor.models import RuntimeModel
from raes_processor.models.runtime_model import ExecutionPlan
from raes_runtime import RuntimeManager, RuntimeTarget

from shared.operation_envelope import MAX_ENVELOPE_BYTES
from shared.raes.artifact_inventory import ArtifactRequirements, ArtifactSupply, build_artifact_supply
from shared.raes.artifact_resolution import ArtifactResolutionStatus, resolve_artifact_requirement
from shared.raes.compiled_participants import CompiledParticipantContext
from shared.raes.manifest import shifter_artifact_mechanism_capabilities, shifter_backend_apparatus

ArtifactSupplyProvider = Callable[
    [ArtifactRequirements], ArtifactSupply | Mapping[str, ArtifactRequirementAvailability]
]


class _RetainedArtifactPlanningInput(BaseModel):
    """Private native admission envelope around the released public planner facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["shifter-artifact-planning-input/v1"] = "shifter-artifact-planning-input/v1"
    raes_version: str
    compiler_input_digest: str
    availability: ArtifactAvailabilityContext
    artifact_mechanisms: tuple[ArtifactMechanismCapability | str, ...]


def capture_artifact_planning_input(execution: ExecutionPlan, context: CompiledParticipantContext) -> bytes:
    """Retain the actual admitted facts; never reconstruct evidence from a binding."""
    declarations = [item for item in execution.manifest.realization_support if item.domain == "runtime-realization"]
    if not execution.is_valid or len(declarations) != 1:
        raise ValueError("Retained artifact planning input unavailable")
    encoded = (
        _RetainedArtifactPlanningInput(
            raes_version=context.raes_version,
            compiler_input_digest=context.compiler_input_digest,
            availability=execution.artifact_availability,
            artifact_mechanisms=declarations[0].artifact_mechanisms,
        )
        .model_dump_json()
        .encode("utf-8")
    )
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ValueError("Retained artifact planning input unavailable")
    return encoded


def restore_artifact_planning_target(
    compiled: RuntimeModel, target: RuntimeTarget, *, context: CompiledParticipantContext
) -> tuple[RuntimeTarget, ArtifactAvailabilityContext]:
    """Reopen an existing realization using its original facts and fixed backend.

    This admits planning only. It neither consults inventory nor authorizes new
    materialization; the persistent control owner supplies a non-dispatching port.
    """
    try:
        requirements = _compiled_requirements(compiled)
        if not context.artifact_planning_json and not requirements:
            return target, ArtifactAvailabilityContext()
        if len(context.artifact_planning_json) > MAX_ENVELOPE_BYTES:
            raise ValueError("Retained input exceeds limit")
        retained = _RetainedArtifactPlanningInput.model_validate_json(context.artifact_planning_json)
        addresses = [item.address for item in retained.availability.requirements]
        if (
            retained.raes_version != context.raes_version
            or retained.compiler_input_digest != context.compiler_input_digest
            or len(addresses) != len(set(addresses))
            or set(addresses) != set(requirements)
            or sum(item.domain == "runtime-realization" for item in target.manifest.realization_support) != 1
        ):
            raise ValueError("Retained admission changed")
        declarations = tuple(
            replace(item, artifact_mechanisms=retained.artifact_mechanisms)
            if item.domain == "runtime-realization"
            else item
            for item in target.manifest.realization_support
        )
        return replace(
            target, manifest=replace(target.manifest, realization_support=declarations)
        ), retained.availability
    except Exception:  # noqa: BLE001  # released validators can include private evidence in their diagnostics
        raise ValueError("Retained artifact planning input unavailable") from None


def _compiled_requirements(compiled: RuntimeModel) -> dict[str, ArtifactRequirement]:
    """Handle compiled requirements."""
    requirements: dict[str, ArtifactRequirement] = {}
    for item in compiled.realization_requirements:
        if item.artifact_requirement is None:
            continue
        if item.address in requirements:
            raise ValueError("compiled artifact requirement address is ambiguous")
        requirements[item.address] = item.artifact_requirement
    return requirements


def _artifact_supply(
    requirements: Mapping[str, ArtifactRequirement],
    supply_provider: ArtifactSupplyProvider | None,
) -> ArtifactSupply:
    """Handle artifact supply."""
    supplied = supply_provider(requirements) if supply_provider is not None and requirements else None
    if isinstance(supplied, ArtifactSupply):
        return supplied
    if supplied is not None:
        return ArtifactSupply(supplied, (), ())
    return build_artifact_supply(requirements, [])


def _availability_facts(
    requirements: Mapping[str, ArtifactRequirement], supply: ArtifactSupply, capabilities: list[str]
) -> list[ArtifactRequirementAvailability]:
    """Handle availability facts."""
    facts = []
    for address, requirement in requirements.items():
        result = resolve_artifact_requirement(
            requirement,
            address=address,
            capabilities=capabilities,
            availability=supply.availability.get(address),
            backend=shifter_backend_apparatus(),
            prepared_materializations=supply.materializations,
        )
        if result.status is not ArtifactResolutionStatus.SATISFIED:
            continue
        disclosure = result.disclosure
        if disclosure is None:
            raise ValueError("satisfied artifact resolution omitted its disclosure")
        facts.append(
            ArtifactRequirementAvailability(
                address=address,
                available_artifact_digests=[disclosure.artifact.digest],
                available_candidate_ids=[disclosure.candidate_id] if disclosure.candidate_id else [],
                verified_locked_input_ids=disclosure.locked_input_ids,
                satisfied_constraint_ids=disclosure.satisfied_constraint_ids,
                available_materialization_specification_digests=(
                    [disclosure.materialization_specification_digest]
                    if disclosure.materialization_specification_digest
                    else []
                ),
                verified_integrity_refs=disclosure.integrity_refs,
                verified_provenance_refs=disclosure.provenance_refs,
            )
        )
    return facts


def prepare_compiled_artifact_target(
    compiled: RuntimeModel,
    target: RuntimeTarget,
    *,
    supply_provider: ArtifactSupplyProvider | None = None,
) -> tuple[RuntimeTarget, ArtifactAvailabilityContext]:
    """Give RAES only complete admitted facts, keyed by its actual compiled addresses.

    Publication requirement addresses and planner resource addresses are different
    public contracts. Compile to obtain the latter; never translate strings or
    copy another requirement's partial availability into this concern.
    """
    requirements = _compiled_requirements(compiled)
    supply = _artifact_supply(requirements, supply_provider)
    capabilities = list(shifter_artifact_mechanism_capabilities())
    for capability in supply.capabilities:
        if capability not in capabilities:
            capabilities.append(capability)
    declarations = tuple(
        replace(declaration, artifact_mechanisms=tuple(capabilities))
        if declaration.domain == "runtime-realization"
        else declaration
        for declaration in target.manifest.realization_support
    )
    target = replace(target, manifest=replace(target.manifest, realization_support=declarations))
    facts = _availability_facts(requirements, supply, capabilities)
    return target, ArtifactAvailabilityContext(requirements=facts)


def plan_with_artifact_supply(
    scenario: Scenario | ExpandedScenario | InstantiatedScenario,
    target: RuntimeTarget,
    *,
    parameters: Mapping[str, object] | None = None,
    supply_provider: ArtifactSupplyProvider | None = None,
) -> tuple[ExecutionPlan, RuntimeTarget]:
    """Plan against the final target with the incumbent admitted artifact facts."""
    compiled = compile_scenario_runtime_model(scenario, parameters=parameters)
    target, availability = prepare_compiled_artifact_target(compiled, target, supply_provider=supply_provider)
    return RuntimeManager(target).plan(scenario, parameters=parameters, artifact_availability=availability), target
