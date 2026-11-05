"""Full native cloud declarations must fit the shared input and cleanup boundary."""

import json
from copy import deepcopy
from uuid import uuid4

import yaml
from cryptography.fernet import Fernet
from raes.scenarios import load_scenario
from raes_runtime import RuntimeManager
from shifter_adapter_sdk.runtime import RuntimePlan

from engine.services._runtime_plugin_cleanup import preparation_cleanup_payload
from engine.services._runtime_plugin_preparation import approved_preparation
from shared.operation_envelope import build_operation_envelope, validate_operation_envelope
from shared.raes.operation_input import (
    RaesInputBindings,
    RaesRangeIdentity,
    build_raes_operation_input,
    parse_raes_operation_input,
)
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests
from tests.shared.raes.test_gcp_project_demands import NeverDispatch
from tests.shared.raes.test_realizability import _cloud_contract


def test_full_native_cloud_input_and_cleanup_cross_the_shared_boundary(tmp_path, settings):
    path = _cloud_contract(tmp_path)
    document = yaml.safe_load(path.read_text())
    runtime = document["nodes"]["web"]["runtime"]
    runtime["identity_authorities"][0]["resource_scopes"][0].update(
        native_id="synthetic-project", incarnation_id="123456789012"
    )
    application = runtime["platform_applications"][0]
    template = application["secrets"][0]
    application["secrets"] = [
        {**deepcopy(template), "secret_id": f"example-{index}", "native_id": f"example-{index}"} for index in range(768)
    ]
    document["realization"] = {"default": "closed"}
    path.write_text(yaml.safe_dump(document))
    scenario = load_scenario(path)
    target = create_shifter_backend_target(port=NeverDispatch(), scenario=scenario)
    execution = RuntimeManager(target).plan(scenario)
    assert not [row for row in execution.diagnostics if row.is_error]
    plan = serialize_provisioning_plan(execution.provisioning)
    operation_id = uuid4()
    pin = RuntimePluginPin(
        organization_uuid=uuid4(),
        installation_id=uuid4(),
        pack_id="synthetic-cloud",
        pack_digest="sha256:" + "a" * 64,
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.prepare",
            "version": "1",
            "distribution": "example-prepare",
            "entry_point": "prepare",
            "worker_image": "registry.example.test/adapter@sha256:" + "b" * 64,
            "capabilities": ["provision.prepare"],
            "required_bindings": [],
            "provisioning_concerns": ["runtime-identity-authorities"],
        },
        bindings={"targets": {}},
    )
    payload = build_raes_operation_input(
        plan=plan,
        bindings=RaesInputBindings(delivery=(), runtime_plugin=pin),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose=None,
        identity=RaesRangeIdentity(7),
    )
    envelope = build_operation_envelope(
        operation_id=operation_id, request_id=uuid4(), resource="raes-range", operation="provision", payload=payload
    )
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    assert 4 * 1024**2 < len(encoded) < 8 * 1024**2
    received = validate_operation_envelope(json.loads(encoded))
    assert parse_raes_operation_input(received["payload"]).plan == plan
    (request,) = runtime_plugin_requests(pin, plan, operation_id, 7, backend="gce")
    result = RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase="prepare",
        status="planned",
    )
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    retained = approved_preparation(request, result, pin, plan)
    cleanup = preparation_cleanup_payload(received, retained)
    destroyed = validate_operation_envelope({**received, "operation": "destroy", "payload": cleanup})
    parsed = parse_raes_operation_input(destroyed["payload"])
    assert parsed.plan == plan
    assert parsed.runtime_preparation == retained
