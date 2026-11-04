"""Native compilation references remain bound to the actual range incarnation."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from raes import parse_sdl
from raes_runtime import RuntimeManager

from engine.models import Range
from engine.services import RangeBindings, create_raes_range, get_range_status
from shared.raes.artifact_planning import capture_artifact_planning_input
from shared.raes.compiled_participants import project_compiled_participants
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan

pytestmark = pytest.mark.django_db
_SCENARIO = Path(__file__).parents[2] / "shared/raes/fixtures/launchable/shifter-launch-access.sdl.yaml"
_PACKAGE_DIGEST = "sha256:" + "b" * 64


class _NoDispatch:
    request_id = "synthetic"

    def realize(self, *args, **kwargs):
        raise AssertionError("Planning must not dispatch")


@pytest.fixture
def compiled_launch(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = ""
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    source = yaml.safe_load(_SCENARIO.read_text())
    source["variables"] = {"note": {"type": "string", "default": "fallback"}}
    scenario = parse_sdl(yaml.safe_dump(source))
    target = create_shifter_backend_target(port=_NoDispatch(), scenario=scenario)
    parameters = {"note": "synthetic-private-parameter"}
    plan = RuntimeManager(target).plan(scenario, parameters=parameters)
    assert plan.is_valid
    context = project_compiled_participants(plan.model, parameters=parameters)
    context = replace(context, artifact_planning_json=capture_artifact_planning_input(plan, context))
    user = get_user_model().objects.create_user(username="compiled-binding@example.com")
    create_raes_range(
        request_id=uuid4(),
        user_id=user.pk,
        workspace_id=1,
        compiled_plan=serialize_provisioning_plan(plan.provisioning),
        bindings=RangeBindings(compiled_participants=context, source_package_digest=_PACKAGE_DIGEST),
    )
    return Range.objects.get(), context


@pytest.fixture
def bound_range(compiled_launch):
    return compiled_launch[0]


def _replay(row, context, package_digest=_PACKAGE_DIGEST):
    return create_raes_range(
        request_id=row.request.request_id,
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        compiled_plan=row.range_config,
        bindings=RangeBindings(compiled_participants=context, source_package_digest=package_digest),
    )


def test_identical_compiler_input_replay_keeps_original_binding(compiled_launch):
    from engine.models import RaesCompilerInputBinding

    row, context = compiled_launch
    original_ref = RaesCompilerInputBinding.objects.get(range=row).binding_ref
    assert _replay(row, context).accepted
    assert RaesCompilerInputBinding.objects.get(range=row).binding_ref == original_ref


@pytest.mark.parametrize(
    "change", ["parameters", "compiler_input", "version", "references", "source", "omitted", "artifact_facts"]
)
def test_compilation_replay_cannot_change_or_omit_retained_input(compiled_launch, change):
    from engine.services import EngineError

    row, context = compiled_launch
    package_digest = _PACKAGE_DIGEST
    if change == "parameters":
        context = replace(context, parameters_json=b'{"note":"different-private-value"}')
    elif change == "compiler_input":
        context = replace(context, compiler_input_digest="sha256:" + "c" * 64)
    elif change == "version":
        context = replace(context, raes_version="0.0.0")
    elif change == "references":
        context = replace(context, participants=())
    elif change == "source":
        package_digest = "sha256:" + "d" * 64
    elif change == "artifact_facts":
        context = replace(context, artifact_planning_json=b"")
    else:
        context = None
    with pytest.raises(EngineError, match="Range compiler input changed"):
        _replay(row, context, package_digest)


def test_compiler_input_is_retained_without_exposing_parameters(bound_range):
    from engine.models import RaesCompilerInputBinding

    binding = RaesCompilerInputBinding.objects.get(range=bound_range)
    assert binding.resource_generation == bound_range.resource_generation
    assert binding.resource_generation is not None
    assert binding.source_package_digest == _PACKAGE_DIGEST
    assert binding.parameters_json == '{"note":"synthetic-private-parameter"}'
    assert binding.artifact_planning_json
    with connection.cursor() as cursor:
        table = connection.ops.quote_name(binding._meta.db_table)
        cursor.execute(f"SELECT parameters_json, artifact_planning_json FROM {table} WHERE id = %s", [binding.pk])
        stored, artifact_facts = cursor.fetchone()
    assert stored.startswith("enc:v1:")
    assert artifact_facts.startswith("enc:v1:")
    assert "synthetic-private-parameter" not in stored
    status = get_range_status(bound_range.pk)
    assert status["compiled_participants"]["participant_refs"] == ["participant.behavior.analyst"]
    assert "synthetic-private-parameter" not in repr(status)
    assert "compiler_input_digest" not in status["compiled_participants"]
    assert "artifact_planning" not in repr(status)


@pytest.mark.parametrize("change", ["resource_generation", "owner_principal_uuid", "workspace_id", "range_config"])
def test_old_compilation_binding_is_not_current_after_custody_changes(bound_range, change):
    value = 2 if change == "workspace_id" else uuid4()
    if change == "range_config":
        value = {**bound_range.range_config, "resources": {}}
    setattr(bound_range, change, value)
    bound_range.save(update_fields=[change])

    assert "compiled_participants" not in get_range_status(bound_range.pk)


def test_reference_projection_does_not_decrypt_selected_parameters(bound_range, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    status = get_range_status(bound_range.pk)
    assert status["compiled_participants"]["participant_refs"] == ["participant.behavior.analyst"]


def test_replay_cannot_upgrade_a_range_without_retained_compiler_input(compiled_launch):
    from engine.models import RaesCompilerInputBinding
    from engine.services import EngineError

    row, context = compiled_launch
    RaesCompilerInputBinding.objects.filter(range=row).delete()
    with pytest.raises(EngineError, match="Range compiler input changed"):
        _replay(row, context)
