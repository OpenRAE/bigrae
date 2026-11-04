"""Open the exact native persistent owner without provisioning resources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from raes.scenarios import load_scenario
from raes_processor.planner import plan

from shared.native_participant import (
    NativeControlAuthorityPort,
    NativePowerControlSelection,
    NativeRuntimeCoordinates,
)
from shared.participant_control_installation import NativeControlBudgets
from shared.raes.artifact_planning import restore_artifact_planning_target
from shared.raes.compiled_participants import CompiledParticipantContext
from shared.raes.native_control_plane import NativeControlPlaneConfiguration, create_native_control_plane
from shared.raes.native_power_authority import NativePowerAuthority
from shared.raes.native_power_candidate import build_native_power_control_candidate
from shared.raes.pack_conformance import ContractValidationPort

if TYPE_CHECKING:
    from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration
    from raes_runtime.participant_control_runtime import ParticipantControlCutResolver
    from raes_runtime.participant_crossing_mediation import (
        ParticipantCrossingPolicyResolver,
    )

    from shared.raes.native_participant_actions import NativePowerReservationPort
    from shared.raes.power_input import NativePowerInput

from shared.raes.native_power_session import NativePowerSession


@dataclass(frozen=True, slots=True, kw_only=True)
class NativePowerSessionConfiguration:
    """Fixed native installation context for this released runtime factory."""

    binding_id: UUID
    scenario_path: Path
    context: CompiledParticipantContext
    coordinates: NativeRuntimeCoordinates
    power: NativePowerInput
    selection: NativePowerControlSelection
    port: NativePowerReservationPort
    store_root: Path
    resolver: ParticipantControlCutResolver | None = None
    crossing_policy_resolver: ParticipantCrossingPolicyResolver | None = None
    source_ref: str
    principal_uuid: UUID
    has_unresolved_invocation: Callable[[], bool]
    supervision: OperationSupervisionConfiguration | None = None
    authority_port: NativeControlAuthorityPort | None = None
    budgets: NativeControlBudgets | None = None
    allow_initialize: bool = True


def _configured_supervision(configuration: NativePowerSessionConfiguration) -> OperationSupervisionConfiguration | None:
    """Resolve installed finite SDK budgets without admitting a second configuration source."""
    budgets, supervision = configuration.budgets, configuration.supervision
    if budgets is not None:
        from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration

        if supervision is not None or not isinstance(budgets, NativeControlBudgets):
            raise ValueError("Native participant runtime budgets unavailable")
        supervision = OperationSupervisionConfiguration(**budgets.model_dump())
    return supervision


def open_native_power_session(configuration: NativePowerSessionConfiguration) -> NativePowerSession:
    """Open one P1 owner, register the original public plan, and preserve its episode."""
    binding_id = configuration.binding_id
    scenario_path = configuration.scenario_path
    context = configuration.context
    coordinates = configuration.coordinates
    power = configuration.power
    selection = configuration.selection
    port = configuration.port
    store_root = configuration.store_root
    resolver = configuration.resolver
    crossing_policy_resolver = configuration.crossing_policy_resolver
    source_ref = configuration.source_ref
    principal_uuid = configuration.principal_uuid
    has_unresolved_invocation = configuration.has_unresolved_invocation
    authority_port = configuration.authority_port
    allow_initialize = configuration.allow_initialize
    supervision = _configured_supervision(configuration)
    scenario = load_scenario(scenario_path)
    candidate = build_native_power_control_candidate(
        scenario=scenario,
        context=context,
        coordinates=coordinates,
        power=power,
        selection=selection,
        dispatch=ContractValidationPort(f"native-control:{coordinates.run_id}"),
        port=port,
    )
    if authority_port is not None:
        if resolver is not None or crossing_policy_resolver is not None or port is not authority_port:
            raise ValueError("Native participant authority configuration unavailable")
        resolver = NativePowerAuthority(binding_id, source_ref, candidate, authority_port)
        crossing_policy_resolver = resolver
    if resolver is None or crossing_policy_resolver is None:
        raise ValueError("Native participant authority configuration unavailable")
    target, availability = restore_artifact_planning_target(candidate.model, candidate.target, context=context)
    runtime = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=target,
            scenario=scenario,
            context=context,
            store_root=store_root,
            coordinates=coordinates,
            resolver=resolver,
            crossing_policy_resolver=crossing_policy_resolver,
            enforce_final_sink_flow_control=False,
            supervision=supervision,
        )
    )
    owner = runtime.owner
    try:
        execution = plan(
            candidate.model,
            target.manifest,
            artifact_availability=availability,
            mixed_control_admission=owner.mixed_control_planning_admission(),
        )
        if not execution.is_valid:
            raise ValueError("Native participant runtime plan unavailable")
        owner.register_planner_produced_plan(execution)
        session = NativePowerSession(
            binding_id, coordinates, selection, source_ref, candidate, owner, runtime.store, has_unresolved_invocation
        )
        episode = owner.snapshot.participant_episode_results.get(selection.participant_address)
        if episode is None:
            if not allow_initialize:
                raise ValueError("Native participant runtime history unavailable")
            with session.mutation():
                receipt = owner.initialize_participant_episode(
                    selection.participant_address,
                    episode_id=session.episode_id,
                    identity=session._identity(principal_uuid),
                    idempotency_key=f"initialize:{coordinates.run_id}",
                )
                status = owner.get_operation(receipt.operation_id)
                if status is None or status.state.value != "succeeded":
                    raise ValueError("Native participant episode unavailable")
        elif episode.get("episode_id") != session.episode_id:
            raise ValueError("Native participant episode unavailable")
        _ = session.cursor
        return session
    except BaseException:
        owner.close()
        raise
