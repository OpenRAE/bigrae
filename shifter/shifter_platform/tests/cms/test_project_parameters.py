"""Project-dependent packs remain portable and require a fenced real selection."""

from uuid import uuid4

import pytest
import yaml

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import pack_digest
from cms.scenarios.registry import _raes_launchable
from engine.models import GcpRangeProject, Range, RuntimePluginInstallation, RuntimePluginPackBinding
from engine.services import (
    install_runtime_plugin,
    project_parameters_for_binding,
    runtime_plugin_file_selection,
    runtime_plugin_plan_parameters,
)
from shared.exceptions import ValidationError
from shared.raes.pack_conformance import validate_pack_contract
from shared.raes.project_parameters import required_project_parameters, select_project_parameters
from shared.raes.realizability import assess_scenario_capability
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginScope
from tests.cms.conftest import write_pack_content_manifest
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_tenant_pack_upload import _post
from tests.cms.test_tenant_pack_upload import upload as upload
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def parameterize(root, *, name="project_number", kind="string"):
    path = root / "sdl/scenario.sdl.yaml"
    document = yaml.safe_load(path.read_text())
    document["variables"] = {name: {"type": kind, "required": True}}
    if name == "project_number" and kind == "string":
        document["nodes"]["web"]["source"]["version"] = "${project_number}"
    path.write_text(yaml.safe_dump(document))
    write_pack_content_manifest(root, root.name)
    return path


@pytest.fixture
def configured_pack(upload, tenant, baseline_ref, request):
    client, organization, root, _ = upload
    actor, _ = tenant
    path = parameterize(root)
    if getattr(request, "param", None) == "restricted":
        document = yaml.safe_load(path.read_text())
        document["variables"]["project_number"]["allowed_values"] = ["9999999999999"]
        path.write_text(yaml.safe_dump(document))
        write_pack_content_manifest(root, root.name)
    response = _post(client, organization, root)
    assert response.status_code == 201, response.data
    source = RaesPackageSource.objects.get()
    project = GcpRangeProject.objects.create(
        id=baseline_ref.registration_id,
        organization_uuid=organization.uuid,
        project_id="synthetic-project",
        project_number="1234567890123",
        status="ready",
        baseline=baseline_ref.model_dump(mode="json"),
        created_by_principal_uuid=actor.credential.principal.uuid,
    )
    manifest = {
        "protocol": "bigrae.runtime-plugin/v2",
        "plugin_id": "example.preparation",
        "version": "1",
        "distribution": "example-adapter",
        "entry_point": "example",
        "worker_image": "registry.example.test/adapter@sha256:" + "a" * 64,
        "capabilities": ["provision.prepare"],
        "provisioning_concerns": ["synthetic-values"],
        "required_bindings": [],
        "required_parameters": ["project-id"],
    }
    installed = install_runtime_plugin(actor.credential, organization.uuid, manifest)
    RuntimePluginInstallation.objects.filter(pk=installed.id).update(state="ready")
    url = f"/api/v1/cms/organizations/{organization.uuid}/plugin-packs/{source.scenario_id}/"
    payload = {
        "installation_id": str(installed.id),
        "pack_digest": source.package_digest,
        "bindings": {"targets": {}, "parameters": {"project-id": project.project_id}},
    }
    scope = RuntimePluginScope(
        organization_uuid=organization.uuid, pack_id=source.scenario_id, pack_digest=source.package_digest
    )
    return client, url, payload, source, project, scope, path


def test_upload_keeps_project_template_pending_and_unlaunchable(upload):
    client, organization, root, _ = upload
    parameterize(root)
    response = _post(client, organization, root)
    assert response.status_code == 201, response.data
    source = RaesPackageSource.objects.get()
    assert response.data["conformance_status"] == source.conformance_status == "pending"
    assert not source.conformance_report_ref
    assert not _raes_launchable(source)
    assert source.package_digest == pack_digest(root)
    assert not Range.objects.exists()


@pytest.mark.parametrize("name,kind", [("arbitrary_input", "string"), ("project_number", "integer")])
def test_upload_rejects_missing_inputs_outside_the_registered_project_contract(upload, name, kind):
    client, organization, root, storage = upload
    parameterize(root, name=name, kind=kind)
    response = _post(client, organization, root)
    assert response.status_code == 400
    assert not RaesPackageSource.objects.exists() and not storage.objects


def test_configuration_runs_real_native_planning_and_preserves_the_pack(configured_pack):
    client, url, payload, source, project, scope, path = configured_pack
    original_digest = source.package_digest
    assert client.get(url).json()["targets"] == []
    response = client.post(url, payload, format="json")
    assert response.status_code == 200, response.data
    source.refresh_from_db()
    assert source.conformance_status == "passed" and _raes_launchable(source)
    assert source.package_digest == original_digest == pack_digest(path.parent.parent)
    captured, facts = runtime_plugin_plan_parameters(scope)
    assert facts == {"project_id": project.project_id, "project_number": project.project_number}
    parameters = select_project_parameters(path, facts)
    assert parameters == {"project_number": project.project_number}
    validate_pack_contract(path, "test-bound-project", parameters=parameters)
    assessment = assess_scenario_capability(path, parameters=parameters)
    assert assessment.image_demands[0].source_version == project.project_number
    assert required_project_parameters(path) == {"project_number"}
    assert captured.binding_digest is not None
    assert client.get(url).json()["targets"]
    assert not Range.objects.exists()


def test_explicit_conformance_uses_the_existing_project_selection(configured_pack, tenant):
    from cms.services._pack_conformance import validate_registered_pack_conformance

    client, url, payload, source, _, _, _ = configured_pack
    actor, _ = tenant
    assert client.post(url, payload, format="json").status_code == 200
    assert validate_registered_pack_conformance(
        user=actor.credential, scenario_id=source.scenario_id, expected_package_digest=source.package_digest
    ) == "passed"


@pytest.mark.parametrize("fault", ["foreign", "disabled", "missing", "bad-number", "wrong-baseline"])
def test_configuration_cannot_promote_an_unavailable_project(configured_pack, fault):
    client, url, payload, source, project, _, _ = configured_pack
    if fault == "disabled":
        project.status = "disabled"
        project.save(update_fields=["status"])
    elif fault == "missing":
        payload["bindings"]["parameters"]["project-id"] = "missing-project"
    else:
        identifier = uuid4()
        GcpRangeProject.objects.create(
            id=identifier,
            organization_uuid=uuid4() if fault == "foreign" else project.organization_uuid,
            project_id="other-project",
            project_number="invalid" if fault == "bad-number" else "2222222222222",
            status="ready",
            baseline={**project.baseline, "registration_id": str(uuid4() if fault == "wrong-baseline" else identifier)},
            created_by_principal_uuid=project.created_by_principal_uuid,
        )
        payload["bindings"]["parameters"]["project-id"] = "other-project"
    response = client.post(url, payload, format="json")
    assert response.status_code == 400
    source.refresh_from_db()
    assert source.conformance_status == "pending"
    assert not RuntimePluginPackBinding.objects.exists()
    assert not Range.objects.exists()


@pytest.mark.parametrize("configured_pack", ["restricted"], indirect=True)
def test_configuration_cannot_promote_a_template_that_fails_native_conformance(configured_pack):
    client, url, payload, source, _, _, _ = configured_pack
    assert client.post(url, payload, format="json").status_code == 400
    source.refresh_from_db()
    assert source.conformance_status == "pending"


@pytest.mark.parametrize("change", ["parameter", "removed", "disabled"])
def test_a_changed_selection_is_fenced_even_without_adapter_files(configured_pack, change):
    client, url, payload, _, _, scope, _ = configured_pack
    assert client.post(url, payload, format="json").status_code == 200
    captured, _ = runtime_plugin_plan_parameters(scope)
    row = RuntimePluginPackBinding.objects.get()
    if change == "removed":
        row.delete()
    elif change == "disabled":
        row.enabled = False
        row.save(update_fields=["enabled"])
    else:
        row.bindings = {**row.bindings, "parameters": {"project-id": "changed-project"}}
        row.save(update_fields=["bindings"])
    with pytest.raises(ValidationError):
        runtime_plugin_plan_parameters(captured)
    with pytest.raises(ValidationError):
        runtime_plugin_file_selection(captured)
    assert not Range.objects.exists()


def test_a_client_cannot_override_the_registered_project_number(configured_pack):
    client, url, payload, source, _, _, _ = configured_pack
    payload["bindings"]["parameters"]["project_number"] = "9999999999999"
    assert client.post(url, payload, format="json").status_code == 400
    source.refresh_from_db()
    assert source.conformance_status == "pending"


def test_project_facts_are_not_general_adapter_parameter_values(configured_pack):
    _, _, _, _, project, scope, _ = configured_pack
    facts = project_parameters_for_binding(
        scope, PluginTargetBindings(targets={}, parameters={"project-id": project.project_id, "private-input": "value"})
    )
    assert set(facts) == {"project_id", "project_number"}
    assert "private-input" not in facts


def test_switching_targets_keeps_pack_bytes_and_rejects_the_original_selection(configured_pack):
    client, url, payload, source, project, scope, path = configured_pack
    assert client.post(url, payload, format="json").status_code == 200
    original, _ = runtime_plugin_plan_parameters(scope)
    identifier = uuid4()
    GcpRangeProject.objects.create(
        id=identifier,
        organization_uuid=project.organization_uuid,
        project_id="second-project",
        project_number="2222222222222",
        status="ready",
        baseline={**project.baseline, "registration_id": str(identifier)},
        created_by_principal_uuid=project.created_by_principal_uuid,
    )
    payload["bindings"]["parameters"]["project-id"] = "second-project"
    assert client.post(url, payload, format="json").status_code == 200
    _, facts = runtime_plugin_plan_parameters(scope)
    assert facts == {"project_id": "second-project", "project_number": "2222222222222"}
    assessment = assess_scenario_capability(path, parameters=select_project_parameters(path, facts))
    assert assessment.image_demands[0].source_version == "2222222222222"
    assert source.package_digest == pack_digest(path.parent.parent)
    with pytest.raises(ValidationError):
        runtime_plugin_plan_parameters(original)
    with pytest.raises(ValidationError):
        runtime_plugin_file_selection(original)


def test_cms_launch_binds_the_selected_number_before_the_actual_native_planner(configured_pack, tenant, monkeypatch):
    from cms.services._raes_dispatch import RaesDispatchOptions, _launch_pack
    from tests.shared.raes.test_package_loader import _RecordingPort

    client, url, payload, source, project, scope, path = configured_pack
    actor, _ = tenant
    assert client.post(url, payload, format="json").status_code == 200
    captured = {}
    port = _RecordingPort()
    port.artifact_supply = lambda requirements: {}

    def recording_port(**kwargs):
        captured.update(kwargs)
        return port

    # Only the side-effect port is replaced. Loading, native instantiation,
    # planning, validation, and the admitted administrator binding stay real.
    monkeypatch.setattr("cms.raes.dispatch.CmsRaesDispatchPort", recording_port)
    _launch_pack(
        uuid4(),
        actor.credential,
        path.parent.parent,
        RaesDispatchOptions(None, None, "status-quo"),
        scope,
        source=source,
    )
    assert len(port.plans) == 1
    node = port.plans[0]["resources"]["provision.node.web"]["payload"]["spec"]["node"]
    assert node["source"]["version"] == project.project_number
    assert captured["runtime_plugin_scope"].binding_digest is not None
