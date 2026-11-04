"""Consumers authenticate retained selections and preserve original reporting identities."""

from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests
from shared.runtime_plugin_preparation import RuntimePreparation
from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

import runtime_plugin_execution as execution
from runtime_plugin_preparation import approved_plan, cleanup_preparation, prepared_run
from tests.test_gcp_project_baselines import capture as capture
from tests.test_gcp_project_baselines import lease
from tests.test_gcp_project_baselines import run as capture_baseline
from tests.test_raes_range_ops import _serialized_plan
from tests.test_raes_range_ops import patched as patched
from tests.test_runtime_plugin_execution import run as run


@pytest.fixture
def approval(run, monkeypatch):
    raw = run.input.runtime_plugin.model_dump(mode="json")
    raw["manifest"]["capabilities"].append("provision.prepare")
    raw["manifest"]["provisioning_concerns"] = ["synthetic-values"]
    pin = RuntimePluginPin.model_validate(raw)
    plan = _serialized_plan()
    plan["operations"] = [
        {
            "address": "node.web",
            "resource_type": "node",
            "action": "create",
            "payload": deepcopy(plan["resources"]["node.web"]["payload"]),
        }
    ]
    plan["realization_authority"] = [
        {
            "address": "node.web",
            "field_path": "name",
            "domain": "provisioning",
            "source": "authored-leaf",
            "payload_pointer": "/name",
            "mode": "open",
            "requirement_kind": "synthetic-values",
        }
    ]
    run = replace(run, input=replace(run.input, plan=plan, runtime_plugin=pin))
    request = runtime_plugin_requests(pin, plan, UUID(run.operation_id), 7)[0]
    result = RuntimePlan(
        protocol=request.protocol,
        phase="prepare",
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        status="planned",
        provisioning_values=[
            {
                "address": "node.web",
                "payload_pointer": "/name",
                "concern": "synthetic-values",
                "value": "private-selection",
            }
        ],
    )
    key = Fernet.generate_key()
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", key.decode())
    snapshot = RuntimePreparation(
        state="prepared",
        plan_digest=canonical_digest(plan),
        pin_digest=pin.digest,
        source_operation_id=request.operation_id,
        input_digest=request.digest,
        encrypted_result="enc:v1:" + Fernet(key).encrypt(result.model_dump_json().encode()).decode(),
    )
    return run, result, snapshot


def test_execution_and_cleanup_use_same_retained_copy_without_changing_original(approval):
    run, result, snapshot = approval
    original = deepcopy(run.input.plan)
    accepted = approved_plan(run, snapshot)
    assert accepted == result
    effective = prepared_run(run, accepted, snapshot)
    assert effective.input.plan["resources"]["node.web"]["payload"]["name"] == "private-selection"
    cleanup, proof = cleanup_preparation(replace(run, input=replace(run.input, runtime_preparation=snapshot)))
    assert proof is None and cleanup.input.plan == effective.input.plan
    assert run.input.plan == original
    assert set(effective.input.plan["resources"]) == set(original["resources"])


@pytest.mark.parametrize("tamper", ["plan", "pin", "source", "digest", "ciphertext", "key", "cleartext"])
def test_invalid_approval_is_rejected_before_any_effect(approval, monkeypatch, tamper):
    run, result, snapshot = approval
    raw = snapshot.model_dump(mode="json")
    if tamper in {"plan", "pin", "digest"}:
        raw[{"plan": "plan_digest", "pin": "pin_digest", "digest": "input_digest"}[tamper]] = "sha256:" + "f" * 64
    elif tamper == "source":
        raw["source_operation_id"] = str(uuid4())
    elif tamper == "ciphertext":
        raw["encrypted_result"] = raw["encrypted_result"][:-3] + "abc"
    elif tamper == "key":
        monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    else:
        raw["encrypted_result"] = result.model_dump_json()
    with pytest.raises(ValueError, match="unavailable") as error:
        approved_plan(run, raw)
    assert "private-selection" not in str(error.value)
    assert error.value.__suppress_context__


def test_retry_uses_original_source_proof_and_does_not_select_again(approval):
    run, result, snapshot = approval
    retry = replace(run, operation_id=str(uuid4()))
    assert approved_plan(retry, snapshot) == result


def test_cleanup_requires_snapshot_and_uses_explicit_pre_effect_proof(approval):
    run, _, snapshot = approval
    with pytest.raises(ValueError, match="unavailable"):
        cleanup_preparation(run)
    absent = RuntimePreparation(state="unprepared", plan_digest=snapshot.plan_digest, pin_digest=snapshot.pin_digest)
    effective, proof = cleanup_preparation(replace(run, input=replace(run.input, runtime_preparation=absent)))
    assert effective.input.plan == run.input.plan
    assert proof["outcome"] == "VERIFIED_ABSENT"
    assert proof["scope"]["proof"] == "runtime-preparation-not-accepted/v1"


def test_prepare_is_separated_from_guest_phases_before_execution(approval, monkeypatch):
    run, _, snapshot = approval

    def response(request):
        if request.phase == "prepare":
            return snapshot.model_dump(mode="json")
        return RuntimePlan(
            protocol=request.protocol,
            invocation_id=request.invocation_id,
            phase=request.phase,
            input_digest=request.digest,
            status="planned",
            actions=[{"action_id": "verify", "binding": "server", "script": "true"}]
            if request.phase == "verify"
            else [],
        ).model_dump(mode="json")

    monkeypatch.setattr(execution, "_read_response", response)
    bundle = execution.load_guest_plugin_plans(run)
    assert bundle.preparation.phase == "prepare"
    assert [request.phase for request in bundle.requests] == ["validate", "configure", "verify"]


def test_malformed_preparation_response_cannot_echo_worker_values(approval, monkeypatch):
    run, _, snapshot = approval
    response = {**snapshot.model_dump(mode="json"), "encrypted_result": "PRIVATE_MALFORMED_VALUE"}
    monkeypatch.setattr(execution, "_read_response", lambda _: response)
    with pytest.raises(execution.RuntimePluginExecutionError, match="planning failed") as error:
        execution.load_guest_plugin_plans(run)
    assert "PRIVATE_MALFORMED_VALUE" not in str(error.value)


def test_range_entry_applies_effective_values_and_reports_original_addresses(approval, patched, monkeypatch):
    import raes_range_ops as ops

    run, result, snapshot = approval
    monkeypatch.setattr(ops, "get_raes_operation_input", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(
        execution, "load_guest_plugin_plans", lambda _: execution.GuestPluginPlans((), (), result, snapshot)
    )
    ops.run_raes_range_provision(run.request_id, operation_id=run.operation_id)
    assert patched.apply.call_args.args[2].nodes[0].name == "private-selection"
    snapshots = [
        call
        for call in patched.append.call_args_list
        if call.kwargs.get("step") == ops.ResultStep.RAES_PROVISION_SNAPSHOT
    ]
    assert snapshots[0].kwargs["result_payload"]["resources"] == [
        {"address": "net.lan", "resource_type": "network", "status": "provisioned"},
        {"address": "node.web", "resource_type": "node", "status": "provisioned"},
    ]
    assert run.input.plan["resources"]["node.web"]["payload"]["name"] == "web"


def test_pre_effect_cleanup_never_creates_provider_clients(approval, patched, monkeypatch):
    import raes_range_ops as ops

    run, _, snapshot = approval
    absent = RuntimePreparation(state="unprepared", plan_digest=snapshot.plan_digest, pin_digest=snapshot.pin_digest)
    run = replace(run, input=replace(run.input, runtime_preparation=absent))
    monkeypatch.setattr(ops, "get_raes_operation_input", lambda *_args, **_kwargs: run)
    ops.run_raes_range_destroy(run.request_id, operation_id=run.operation_id)
    patched.load_config.assert_not_called()
    patched.destroy.assert_not_called()
    assert patched.append.call_args.kwargs["result_payload"]["cleanup_inventory"]["outcome"] == "VERIFIED_ABSENT"


def test_unprepared_cleanup_proof_must_match_the_original_plan(approval):
    run, _, snapshot = approval
    absent = RuntimePreparation(state="unprepared", pin_digest=snapshot.pin_digest, plan_digest="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="unavailable"):
        cleanup_preparation(replace(run, input=replace(run.input, runtime_preparation=absent)))


def test_provision_and_destroy_keep_same_host_approved_project_references(approval, capture):
    run, result, snapshot = approval
    binding = lease(capture, capture_baseline(capture)).model_copy(
        update={
            "request_id": UUID(run.request_id),
            "range_id": run.input.legacy_range_id,
            "plan_digest": snapshot.plan_digest,
            "source_operation_id": snapshot.source_operation_id,
        }
    )
    snapshot = RuntimePreparation.model_validate({**snapshot.model_dump(), "cloud_projects": (binding,)})
    effective = prepared_run(run, approved_plan(run, snapshot), snapshot)
    destroy = replace(
        run, operation_id=str(uuid4()), input=replace(run.input, runtime_preparation=snapshot, gcp_projects=(binding,))
    )
    cleanup, proof = cleanup_preparation(destroy)
    assert proof is None
    assert effective.input.gcp_projects == cleanup.input.gcp_projects == (binding,)
    assert effective.input.plan == cleanup.input.plan
    assert not run.input.gcp_projects and run.input.runtime_preparation is None
    foreign = replace(run, request_id=str(uuid4()))
    with pytest.raises(ValueError, match="unavailable"):
        prepared_run(foreign, result, snapshot)
