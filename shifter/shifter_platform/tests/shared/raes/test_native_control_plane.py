"""Released P1 stores retain one native binding/run and exclude competing owners.

The SDK reference participant component is used only to exercise episode
persistence. These tests establish no native world-effect capability.
"""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from raes import parse_sdl_file
from raes_backend_protocols.participant_capabilities import ParticipantRuntimeCapabilities
from raes_backend_protocols.participant_runtime_base import BaseParticipantRuntime
from raes_contracts.errors import ConflictError
from raes_processor.compiler import compile_scenario_runtime_model
from raes_runtime.control_plane_security import ControlPlaneIdentity, ControlPlaneRole
from raes_runtime.participant_control_runtime import ParticipantControlLiveCut

from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.native_control_plane import NativeControlPlaneConfiguration
from shared.raes.runtime_target import create_shifter_backend_target

_SCENARIO = Path(__file__).parent / "fixtures/control/participant-supervision.sdl.yaml"


class _UnusedDispatch:
    request_id = "synthetic"

    def realize(self, *args, **kwargs):
        raise AssertionError("Episode persistence must not provision resources")


class _FixtureCutResolver:
    def resolve_cut(self, *args):
        return ParticipantControlLiveCut(
            request_ref="synthetic:initial-authority",
            effective_order=0,
            active_authority_basis_refs=["entities.analyst-team"],
            authorized_scope_refs=["provision.node.web"],
            evidence_refs=["synthetic:admission-evidence"],
        )


@pytest.fixture
def configuration(tmp_path):
    from shared.raes.native_control_plane import NativeRuntimeCoordinates

    scenario = parse_sdl_file(_SCENARIO)
    context = project_compiled_participants(compile_scenario_runtime_model(scenario))
    return {
        "target": _target(scenario),
        "scenario": scenario,
        "context": context,
        "store_root": tmp_path,
        "coordinates": NativeRuntimeCoordinates(binding_ref=uuid4(), resource_generation=uuid4(), run_id=uuid4()),
        "resolver": _FixtureCutResolver(),
    }


def _target(scenario):
    generic = create_shifter_backend_target(port=_UnusedDispatch(), scenario=scenario)
    return replace(
        generic,
        participant_runtime=BaseParticipantRuntime(),
        manifest=replace(
            generic.manifest,
            capabilities=replace(
                generic.manifest.capabilities,
                participant_runtime=ParticipantRuntimeCapabilities(name="synthetic-episodes"),
            ),
        ),
    )


def test_reopened_owner_recovers_the_released_episode_snapshot(configuration):
    from shared.raes.native_control_plane import create_native_control_plane

    identity = ControlPlaneIdentity(identity="synthetic-operator", roles=frozenset({ControlPlaneRole.OPERATOR}))
    first = create_native_control_plane(NativeControlPlaneConfiguration(**configuration)).owner
    try:
        first.initialize_participant_episode(
            "participant.behavior.analyst",
            episode_id="episode:synthetic",
            identity=identity,
            idempotency_key="initialize:synthetic",
        )
        expected = first.snapshot.participant_episode_results
        assert expected["participant.behavior.analyst"]["episode_id"] == "episode:synthetic"
    finally:
        first.close()
    recovered = create_native_control_plane(
        NativeControlPlaneConfiguration(**{**configuration, "target": _target(configuration["scenario"])})
    ).owner
    try:
        assert recovered.snapshot.participant_episode_results == expected
    finally:
        recovered.close()


def test_same_binding_generation_and_run_cannot_have_two_owners(configuration):
    from shared.raes.native_control_plane import create_native_control_plane

    first = create_native_control_plane(NativeControlPlaneConfiguration(**configuration)).owner
    try:
        with pytest.raises(ConflictError):
            create_native_control_plane(
                NativeControlPlaneConfiguration(**{**configuration, "target": _target(configuration["scenario"])})
            )
        assert first.snapshot.participant_episode_results == {}
    finally:
        first.close()


@pytest.mark.parametrize("dimension", ["binding_ref", "resource_generation", "run_id"])
def test_distinct_native_coordinates_never_share_a_runtime_store(configuration, dimension):
    from shared.raes.native_control_plane import create_native_control_plane

    first = create_native_control_plane(NativeControlPlaneConfiguration(**configuration)).owner
    second = create_native_control_plane(
        NativeControlPlaneConfiguration(
            **{
                **configuration,
                "target": _target(configuration["scenario"]),
                "coordinates": replace(configuration["coordinates"], **{dimension: uuid4()}),
            }
        )
    ).owner
    try:
        assert first.snapshot.participant_episode_results == second.snapshot.participant_episode_results == {}
        assert len(list(configuration["store_root"].rglob("control-plane.sqlite3"))) == 2
    finally:
        second.close()
        first.close()


def test_provisioning_only_target_cannot_acquire_a_participant_runtime_owner(configuration):
    from shared.raes.native_control_plane import create_native_control_plane

    target = create_shifter_backend_target(port=_UnusedDispatch(), scenario=configuration["scenario"])
    with pytest.raises(ValueError, match="Installed participant runtime is unavailable"):
        create_native_control_plane(NativeControlPlaneConfiguration(**{**configuration, "target": target}))
    assert not list(configuration["store_root"].rglob("control-plane.sqlite3"))


def test_public_planner_uses_the_exact_installed_native_consumer_context(configuration):
    from raes_processor.planner import plan

    from shared.raes.compiled_participants import restore_compiled_model
    from shared.raes.native_control_plane import create_native_control_plane

    owner = create_native_control_plane(NativeControlPlaneConfiguration(**configuration)).owner
    try:
        admission = owner.mixed_control_planning_admission()
        canonical = restore_compiled_model(configuration["scenario"], configuration["context"])
        execution = plan(canonical, configuration["target"].manifest, mixed_control_admission=admission)
        assert execution.is_valid, [(diagnostic.code, diagnostic.message) for diagnostic in execution.diagnostics]
        assert owner.register_planner_produced_plan(execution)
    finally:
        owner.close()


def test_runtime_limits_must_use_the_published_bounded_configuration(configuration):
    from shared.raes.native_control_plane import create_native_control_plane

    with pytest.raises(ValueError, match="Native runtime limits are unavailable"):
        create_native_control_plane(NativeControlPlaneConfiguration(**configuration, supervision={"admission_ms": 0}))
    assert not list(configuration["store_root"].rglob("control-plane.sqlite3"))
