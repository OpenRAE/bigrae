"""Install a released durable runtime for one admitted native binding and run.

The owning worker supplies verified native coordinates, an independently
authorized immutable source, an installed target and a live authority resolver.
Neither this factory nor compilation metadata grants product authorization or
advertises participant-control support. Keep the returned owner alive for its
worker context and close it through the SDK before releasing that context.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from raes_processor.semantics.realization import materialize_realization_requirements
from raes_runtime.control_plane import RuntimeControlPlane
from raes_runtime.control_plane_profiles import ControlPlaneProfile
from raes_runtime.control_plane_store_local import LocalControlPlaneStore
from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration
from raes_runtime.participant_control_runtime import MixedControlRuntimeBinding

from shared.native_participant import NativeRuntimeCoordinates
from shared.raes.compiled_participants import CompiledParticipantContext, restore_compiled_model

if TYPE_CHECKING:
    from raes.scenarios import Scenario
    from raes_processor.models import ExecutionPlan, RuntimeModel
    from raes_processor.planner.mixed_control_admission import MixedControlPlanningAdmission
    from raes_runtime.participant_control_runtime import ParticipantControlCutResolver
    from raes_runtime.participant_crossing_mediation import ParticipantCrossingPolicyResolver
    from raes_runtime.registry import RuntimeTarget


__all__ = ["NativeControlPlanner", "NativeRuntimeCoordinates", "create_native_control_plane", "native_control_planner"]


@dataclass(frozen=True, slots=True)
class NativeControlRuntime:
    """Retain the released owner and its public store for original receipt lookup."""

    owner: RuntimeControlPlane = field(repr=False)
    store: LocalControlPlaneStore = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeControlPlanner:
    """Expose matching planning admission and registration, without effect APIs."""

    _owner: RuntimeControlPlane = field(repr=False)

    @property
    def admission(self) -> MixedControlPlanningAdmission:
        """Obtain the released owner's admission for its exact installed context."""
        return self._owner.mixed_control_planning_admission()

    def register(self, execution: ExecutionPlan) -> None:
        """Register the exact public-planner result before native dispatch."""
        self._owner.register_planner_produced_plan(execution)


def _compiled_control_model(
    target: RuntimeTarget, scenario: Scenario, context: CompiledParticipantContext
) -> RuntimeModel:
    if target.participant_runtime is None or target.manifest.participant_runtime is None:
        raise ValueError("Installed participant runtime is unavailable")
    model = restore_compiled_model(scenario, context)
    return replace(
        model,
        realization_requirements=materialize_realization_requirements(model.realization_requirements, target.manifest),
    )


@contextmanager
def native_control_planner(
    *,
    target: RuntimeTarget,
    scenario: Scenario,
    context: CompiledParticipantContext,
    resolver: ParticipantControlCutResolver,
    crossing_policy_resolver: ParticipantCrossingPolicyResolver | None = None,
    enforce_final_sink_flow_control: bool = True,
) -> Iterator[NativeControlPlanner]:
    """Expose only P0 planning admission, never an ephemeral execution service.

    The target's components belong only to this bounded planning owner. Build
    fresh components when the qualified generation opens its P1 owner. No
    lifecycle or effect method is exposed and no episode is initialized here.
    """
    model = _compiled_control_model(target, scenario, context)
    owner = RuntimeControlPlane(
        target,
        profile=ControlPlaneProfile.P0,
        mixed_control=MixedControlRuntimeBinding(model=model, resolver=resolver),
        behavior_specifications=model.behavior_specifications,
        participant_outcome_model=model,
        crossing_policy_resolver=crossing_policy_resolver,
        enforce_final_sink_flow_control=enforce_final_sink_flow_control,
    )
    try:
        yield NativeControlPlanner(owner)
    finally:
        owner.close()


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeControlPlaneConfiguration:
    """Fixed native installation context for this released runtime factory."""

    target: RuntimeTarget
    scenario: Scenario
    context: CompiledParticipantContext
    store_root: Path
    coordinates: NativeRuntimeCoordinates
    resolver: ParticipantControlCutResolver
    supervision: OperationSupervisionConfiguration | None = None
    crossing_policy_resolver: ParticipantCrossingPolicyResolver | None = None
    enforce_final_sink_flow_control: bool = True


def create_native_control_plane(configuration: NativeControlPlaneConfiguration) -> NativeControlRuntime:
    """Retain the SDK's P1 owner and store; they own history, claims and recovery.

    The native caller must fence these coordinates against current custody and
    resource generation before installation and on consequential operations.
    The storage root is installation-owned protected local block storage, never
    a pack path, a caller path, or a shared network filesystem.
    """
    target = configuration.target
    scenario = configuration.scenario
    context = configuration.context
    store_root = configuration.store_root
    coordinates = configuration.coordinates
    resolver = configuration.resolver
    supervision = configuration.supervision
    crossing_policy_resolver = configuration.crossing_policy_resolver
    enforce_final_sink_flow_control = configuration.enforce_final_sink_flow_control
    if target.participant_runtime is None or target.manifest.participant_runtime is None:
        raise ValueError("Installed participant runtime is unavailable")
    if not isinstance(store_root, Path) or not store_root.is_absolute():
        raise ValueError("Native runtime storage is unavailable")
    limits = OperationSupervisionConfiguration() if supervision is None else supervision
    if not isinstance(limits, OperationSupervisionConfiguration):
        raise ValueError("Native runtime limits are unavailable")
    # The public planner compares its executable demand graph with the exact
    # installed consumer. Resolve the SDK's closed apparatus defaults before
    # binding that consumer, rather than treating raw compiler metadata as the
    # executable context or relaxing the planner's equality check.
    model = _compiled_control_model(target, scenario, context)
    binding = MixedControlRuntimeBinding(model=model, resolver=resolver)
    path = store_root / str(coordinates.binding_ref) / str(coordinates.resource_generation) / str(coordinates.run_id)
    store = LocalControlPlaneStore(path)
    try:
        owner = RuntimeControlPlane(
            target,
            store=store,
            profile=ControlPlaneProfile.P1,
            supervision=limits,
            run_scope=f"run:{coordinates.run_id}",
            mixed_control=binding,
            behavior_specifications=model.behavior_specifications,
            participant_outcome_model=model,
            crossing_policy_resolver=crossing_policy_resolver,
            enforce_final_sink_flow_control=enforce_final_sink_flow_control,
        )
        return NativeControlRuntime(owner, store)
    except Exception:
        # An unsuccessful constructor must not strand this store's own lease.
        # A successful owner is closed only by RuntimeControlPlane.close(),
        # which retains ownership when a native callback has not drained.
        store.close()
        raise
