"""Released SDL -> native plan -> literal provider operations and sealed payloads."""

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
import yaml
from cryptography.fernet import Fernet
from raes.instantiate import instantiate_scenario
from raes.scenarios import load_scenario
from raes_runtime import RuntimeManager
from shifter_adapter_sdk.runtime import canonical_digest

from shared.field_encryption import decrypt_value
from shared.gcp_cloud_content import open_cloud_content
from shared.gcp_range_projects import GcpProjectLease
from shared.gcp_runtime_plan import compile_cloud_work, selected_secret_payloads
from shared.raes.cloud_content import prepare_cloud_content, referenced_cloud_content
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan
from tests.shared.raes.test_gcp_project_demands import NeverDispatch
from tests.shared.raes.test_realizability import _cloud_contract
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref


@pytest.fixture
def cloud_plan(tmp_path, baseline_ref, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    path = _cloud_contract(tmp_path)
    document = yaml.safe_load(path.read_text())
    node = document["nodes"]["web"]
    authority = node["runtime"]["identity_authorities"][0]
    scope_ref = "nodes.web.runtime.identity_authorities.cloud-iam.resource_scopes.project"
    subject_ref = "nodes.web.runtime.identity_authorities.cloud-iam.subjects.reader"
    role_ref = "nodes.web.runtime.identity_authorities.cloud-iam.subjects.read-role"
    secret_ref = "nodes.web.runtime.platform_applications.secret-service.secrets.example"
    authority["resource_scopes"][0].update(native_id="synthetic-project", incarnation_id="123456789012")
    authority["subjects"] = [
        {
            "subject_id": "reader",
            "kind": "service_account",
            "name": "reader-sa",
            "principal_name": "reader-sa@synthetic-project.iam.gserviceaccount.com",
            "display_name": "Exact display ${literal}",
            "description": "Exact description",
            "enabled": True,
            "resource_scope_ref": scope_ref,
        },
        {"subject_id": "read-role", "kind": "role", "name": "roles/secretmanager.secretAccessor"},
    ]
    authority["policies"] = [
        {
            "policy_id": "read-secret",
            "policy_kind": "access",
            "resource_access": {
                "attachment_ref": secret_ref,
                "bindings": [
                    {
                        "binding_id": "read",
                        "principal_refs": [subject_ref],
                        "resource_refs": [secret_ref],
                        "role_ref": role_ref,
                        "effect": "allow",
                    }
                ],
            },
        }
    ]
    secret = node["runtime"]["platform_applications"][0]["secrets"][0]
    secret["versions"][0]["payload_content_ref"] = "content.payload"
    document["content"] = {
        "payload": {
            "type": "file",
            "target": "web",
            "path": "/opt/synthetic/payload.txt",
            "text": "literal café\n",
            "sensitive": True,
        }
    }
    # The display contains a literal Terraform template opener. RAE itself
    # reserves ${name}; use a different exact label for public instantiation.
    authority["subjects"][0]["display_name"] = "Exact display name"
    path.write_text(yaml.safe_dump(document))
    instantiated = instantiate_scenario(load_scenario(path))
    target = create_shifter_backend_target(port=NeverDispatch(), scenario=instantiated)
    plan = serialize_provisioning_plan(RuntimeManager(target).plan(instantiated).provisioning)
    sealed = prepare_cloud_content(referenced_cloud_content(instantiated), plan, None)
    contents = open_cloud_content(sealed, plan, decrypt_value)
    lease = GcpProjectLease(
        lease_id=uuid4(),
        source_operation_id=uuid4(),
        project_id="synthetic-project",
        project_number="123456789012",
        organization_uuid=uuid4(),
        range_uuid=uuid4(),
        range_id=7,
        request_id=uuid4(),
        plan_digest=canonical_digest(plan),
        baseline=baseline_ref,
    )
    return plan, lease, contents, sealed


def test_native_cloud_graph_retains_exact_identities_grants_and_literal_content(cloud_plan):
    plan, lease, contents, sealed = cloud_plan
    (work,) = compile_cloud_work(plan, (lease,), contents)
    assert work.accounts == {
        "reader-sa@synthetic-project.iam.gserviceaccount.com": {
            "account_id": "reader-sa",
            "display_name": "Exact display name",
            "description": "Exact description",
            "disabled": False,
        }
    }
    assert work.secrets["example"]["versions"][0]["payload"] == "literal café\n".encode()
    assert work.grants == [
        {
            "kind": "secret",
            "target": "example",
            "role": "roles/secretmanager.secretAccessor",
            "member": "serviceAccount:reader-sa@synthetic-project.iam.gserviceaccount.com",
            "condition": None,
        }
    ]
    assert work.audits == [{"service": "secretmanager.googleapis.com", "log_type": "DATA_READ", "exempted_members": []}]
    assert "literal café" not in sealed.model_dump_json()


@pytest.mark.parametrize("change", ["provider", "role", "action", "missing-content", "existing-claim", "extra-field"])
def test_unsupported_intent_is_rejected_before_provider_work(cloud_plan, change):
    original, lease, contents, _ = cloud_plan
    plan = deepcopy(original)
    runtime = plan["resources"]["provision.node.web"]["payload"]["spec"]["node"]["runtime"]
    authority = runtime["identity_authorities"][0]
    if change == "provider":
        authority["resource_scopes"][0]["provider"] = "aws"
    elif change == "role":
        authority["subjects"][1]["name"] = "projects/other/roles/custom"
    elif change == "action":
        authority["policies"][0]["resource_access"]["bindings"][0]["effect"] = "deny"
    elif change == "missing-content":
        contents = {}
    elif change == "existing-claim":
        authority["resource_scopes"][0]["incarnation_id"] = "111122223333"
    else:
        runtime["platform_applications"][0]["settings"] = [{"name": "unsupported", "value": "present"}]
    with pytest.raises(ValueError, match=r"unsupported|unresolved"):
        compile_cloud_work(plan, (lease,), contents)


def test_sealed_content_cannot_move_to_another_plan(cloud_plan):
    plan, _, _, sealed = cloud_plan
    with pytest.raises(ValueError, match="unavailable"):
        open_cloud_content(sealed, {**plan, "operation_id": str(uuid4())}, decrypt_value)


@pytest.mark.parametrize("selected,accepted", [("other-project", True), ("outside-project", False)])
def test_preparation_evaluates_the_published_native_concern_projection(tmp_path, selected, accepted):
    from shifter_adapter_sdk.runtime import RuntimePlan

    from shared.raes.runtime_preparation import validate_runtime_preparation
    from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests

    path = _cloud_contract(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["variables"] = {
        "range_project": {
            "type": "string",
            "default": "synthetic-project",
            "allowed_values": ["synthetic-project", "other-project"],
        }
    }
    authority = document["nodes"]["web"]["runtime"]["identity_authorities"][0]
    authority["resource_scopes"][0]["native_id"] = "${range_project}"
    path.write_text(yaml.safe_dump(document))
    scenario = instantiate_scenario(load_scenario(path))
    target = create_shifter_backend_target(port=NeverDispatch(), scenario=scenario)
    plan = serialize_provisioning_plan(RuntimeManager(target).plan(scenario).provisioning)
    pin = RuntimePluginPin(
        organization_uuid=uuid4(),
        installation_id=uuid4(),
        pack_id="synthetic",
        pack_digest="sha256:" + "a" * 64,
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.prepare",
            "version": "1",
            "distribution": "example-prepare",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "b" * 64,
            "capabilities": ["provision.prepare"],
            "required_bindings": [],
            "provisioning_concerns": ["runtime-identity-authorities"],
        },
        bindings={"targets": {}},
    )
    (request,) = runtime_plugin_requests(pin, plan, uuid4(), 7)
    result = RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase="prepare",
        status="planned",
        provisioning_values=[
            {
                "address": "provision.node.web",
                "concern": "runtime-identity-authorities",
                "payload_pointer": "/spec/node/runtime/identity_authorities/0/resource_scopes/0/native_id",
                "value": selected,
            }
        ],
    )
    if accepted:
        effective = validate_runtime_preparation(plan, result, pin)
        runtime = effective["resources"]["provision.node.web"]["payload"]["spec"]["node"]["runtime"]
        scope = runtime["identity_authorities"][0]["resource_scopes"][0]
        assert scope["native_id"] == selected
        assert plan["resources"] != effective["resources"]
    else:
        with pytest.raises(ValueError, match="Preparation does not conform"):
            validate_runtime_preparation(plan, result, pin)


def test_preparation_can_fill_only_an_unbound_native_secret_payload(cloud_plan):
    from shifter_adapter_sdk.runtime import RuntimePlan

    plan, lease, _contents, _sealed = cloud_plan
    native_version_ref = "nodes.web.runtime.platform_applications.secret-service.secrets.example.versions.v1"
    result = RuntimePlan(
        protocol="shifter.runtime-plugin/v1",
        invocation_id=uuid4(),
        input_digest="sha256:" + "a" * 64,
        phase="prepare",
        status="planned",
        secret_payloads=[{"version_ref": native_version_ref, "value": "chosen café\n"}],
    )
    with pytest.raises(ValueError):
        selected_secret_payloads(plan, result, ["runtime-platform-applications"])
    candidate = deepcopy(plan)
    runtime = candidate["resources"]["provision.node.web"]["payload"]["spec"]["node"]["runtime"]
    runtime["platform_applications"][0]["secrets"][0]["versions"][0]["payload_content_ref"] = ""
    contents = selected_secret_payloads(candidate, result, ["runtime-platform-applications"])
    (work,) = compile_cloud_work(candidate, (lease,), contents)
    assert work.secrets["example"]["versions"][0]["payload"] == "chosen café\n".encode()
    with pytest.raises(ValueError):
        selected_secret_payloads(candidate, result, ["content-placement"])


@pytest.fixture
def logical_cloud_plan(tmp_path, cloud_plan):
    _original, lease, contents, _sealed = cloud_plan
    document = yaml.safe_load((tmp_path / "synthetic-cloud.sdl.yaml").read_text())
    runtime = document["nodes"]["web"].pop("runtime")
    document["nodes"]["web"].update(os_distribution="ubuntu", os_version="22.04", source={"name": "ubuntu"})
    document["nodes"]["cloud"] = {"type": "compute", "runtime": runtime}
    # Rewrite native declaration references while preserving the guest target.
    path = tmp_path / "logical-cloud.sdl.yaml"
    path.write_text(yaml.safe_dump(document).replace("nodes.web.runtime", "nodes.cloud.runtime"))
    scenario = instantiate_scenario(load_scenario(path))
    target = create_shifter_backend_target(port=NeverDispatch(), scenario=scenario)
    plan = replace(RuntimeManager(target).plan(scenario).provisioning, operation_id=str(uuid4()))
    serialized = serialize_provisioning_plan(plan, backend_realization_envelope=target.manifest.realization_envelope)
    lease = lease.model_copy(update={"plan_digest": canonical_digest(serialized)})
    return plan, serialized, compile_cloud_work(serialized, (lease,), contents)


def test_cloud_only_node_keeps_native_identity_without_adding_a_vm(logical_cloud_plan):
    import sys
    from pathlib import Path

    from shared.gcp_runtime_plan import cloud_only_node_addresses

    _plan, serialized, _work = logical_cloud_plan
    assert cloud_only_node_addresses(serialized) == {"provision.node.cloud"}
    # The consumer projection is exercised through its native reader, with no provider.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "engine/provisioner"))
    try:
        from raes_plan import parse_plan
        from raes_snapshot import snapshot_resources

        projected = parse_plan(serialized, cloud_admitted=True)
        assert [node.address for node in projected.nodes] == ["provision.node.web"]
        assert [node.address for node in projected.cloud_nodes] == ["provision.node.cloud"]
        coverage = snapshot_resources(projected, {item.address for item in projected.content})
        assert {row["address"] for row in coverage} == set(serialized["resources"])
    finally:
        sys.path.pop(0)


def test_cloud_completion_requires_bound_readback_and_only_actual_guest_os(logical_cloud_plan):
    from shared.gcp_project_completion import cloud_configuration_digest
    from shared.raes.completion import completed_snapshot
    from shared.raes.completion_evidence import build_completion_evidence

    plan, serialized, work = logical_cloud_plan
    proofs = [
        {
            "lease_id": str(row.lease.lease_id),
            "project_id": row.lease.project_id,
            "configuration_digest": cloud_configuration_digest(row),
            "observed_state_digest": "sha256:" + "a" * 64,
        }
        for row in work
    ]
    evidence = build_completion_evidence(
        serialized,
        resources=[
            {
                "address": address,
                "resource_type": row["resource_type"],
                "status": "provisioned" if row["resource_type"] in {"node", "network"} else "verified",
            }
            for address, row in serialized["resources"].items()
        ],
        operating_systems=[
            {"instance_key": "provision.node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
        ],
        compute_substrates=[{"instance_key": "provision.node.web#0", "value": "virtual-machine"}],
        cloud_projects=proofs,
    )
    snapshot = completed_snapshot(plan, evidence, serialized_plan=serialized, cloud_context=(serialized, work))
    assert "provision.node.cloud" in snapshot.entries
    with pytest.raises(ValueError, match="retained execution context"):
        completed_snapshot(plan, evidence, serialized_plan=serialized)
    changed = deepcopy(evidence)
    changed["cloud_projects"][0]["configuration_digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="another configuration"):
        completed_snapshot(plan, changed, serialized_plan=serialized, cloud_context=(serialized, work))


@pytest.mark.parametrize("declaration", ["os", "image", "hardware", "substrate"])
def test_declared_guest_demands_are_never_projected_as_cloud_only(logical_cloud_plan, declaration):
    from shared.gcp_runtime_plan import cloud_only_node_addresses

    _plan, original, _work = logical_cloud_plan
    plan = deepcopy(original)
    payload = plan["resources"]["provision.node.cloud"]["payload"]
    if declaration == "os":
        payload["os_family"] = "linux"
    elif declaration == "image":
        payload["spec"]["node"]["source"] = {"name": "ubuntu"}
    elif declaration == "hardware":
        payload["spec"]["node"]["resources"] = {"cpu": 2}
    else:
        plan["realization_constraints"].append({"address": "provision.node.cloud"})
    assert not cloud_only_node_addresses(plan)
