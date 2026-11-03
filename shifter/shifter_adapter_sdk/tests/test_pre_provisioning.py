"""Preparation is explicitly declared, bounded and confidential before host admission."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from shifter_adapter_sdk import runtime, worker


def request_payload():
    return {
        "protocol": runtime.PROTOCOL,
        "invocation_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "pack_digest": "sha256:" + "a" * 64,
        "phase": "prepare",
        "provider": "gcp",
        "range_id": 1,
        "targets": {},
        "parameters": {},
        "plan_digest": "sha256:" + "b" * 64,
        "manifest": {
            "protocol": runtime.PROTOCOL,
            "plugin_id": "example.prepare",
            "version": "1",
            "distribution": "example-prepare",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "c" * 64,
            "capabilities": ["provision.prepare"],
            "required_bindings": [],
            "provisioning_concerns": ["synthetic-values"],
        },
    }


def planned(request, **changes):
    return runtime.RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase=request.phase,
        status="planned",
        provisioning_values=[
            {
                "address": "node.example",
                "concern": "synthetic-values",
                "payload_pointer": "/settings/value",
                "value": "PRIVATE_SUPPLIED_VALUE",
            }
        ],
        **changes,
    )


def test_preparation_only_adapter_uses_explicit_closed_inputs():
    request = runtime.RuntimeInput.model_validate(request_payload())
    response = planned(request)
    response.authorize(request)
    assert request.targets == {}
    assert response.provisioning_values[0].value == "PRIVATE_SUPPLIED_VALUE"
    assert "PRIVATE_SUPPLIED_VALUE" not in repr(response)


@pytest.mark.parametrize("change", ["digest", "capability", "concern", "guest-phase"])
def test_preparation_requires_its_plan_digest_and_explicit_capability(change):
    value = request_payload()
    if change == "digest":
        value.pop("plan_digest")
    elif change == "capability":
        value["manifest"]["capabilities"] = ["guest.verify"]
    elif change == "concern":
        value["manifest"]["provisioning_concerns"] = []
    else:
        value["phase"] = "configure"
    with pytest.raises(ValueError):
        runtime.RuntimeInput.model_validate(value)


@pytest.mark.parametrize("change", ["duplicate", "path", "concern", "actions", "failed-values"])
def test_preparation_response_cannot_expand_its_authorized_shape(change):
    request = runtime.RuntimeInput.model_validate(request_payload())
    value = planned(request).model_dump(mode="json")
    if change == "duplicate":
        value["provisioning_values"] *= 2
    elif change == "path":
        value["provisioning_values"][0]["payload_pointer"] = "../settings"
    elif change == "concern":
        value["provisioning_values"][0]["concern"] = "undeclared"
    elif change == "actions":
        value["actions"] = [{"action_id": "run", "binding": "server", "script": "exit 0"}]
    else:
        value.update(status="failed", failure_code="planning-failed")
    with pytest.raises(ValueError):
        runtime.RuntimePlan.model_validate(value).authorize(request)


def test_worker_encrypts_preparation_before_stdout(monkeypatch, capsys):
    request = runtime.RuntimeInput.model_validate(request_payload())
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BIGRAE_PLUGIN_INPUT", request.model_dump_json())
    monkeypatch.setenv(runtime.PREPARATION_OUTPUT_ENV, key)
    monkeypatch.setattr(worker, "_load_plugin", lambda _manifest: SimpleNamespace(plan=planned))
    assert worker.main() == 0
    captured = capsys.readouterr()
    assert "PRIVATE_SUPPLIED_VALUE" not in captured.out + captured.err
    assert runtime.parse_result(captured.out, request, result_secret=key) == planned(request)
    with pytest.raises(ValueError):
        runtime.parse_result(captured.out, request, result_secret=Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        runtime.parse_result(planned(request).model_dump_json(), request, result_secret=key)


def test_missing_output_secret_never_prints_clear_preparation(monkeypatch, capsys):
    request = runtime.RuntimeInput.model_validate(request_payload())
    monkeypatch.setenv("BIGRAE_PLUGIN_INPUT", request.model_dump_json())
    monkeypatch.delenv(runtime.PREPARATION_OUTPUT_ENV, raising=False)
    monkeypatch.setattr(worker, "_load_plugin", lambda _manifest: SimpleNamespace(plan=planned))
    assert worker.main() == 2
    captured = capsys.readouterr()
    assert "PRIVATE_SUPPLIED_VALUE" not in captured.out + captured.err
    assert not captured.out
