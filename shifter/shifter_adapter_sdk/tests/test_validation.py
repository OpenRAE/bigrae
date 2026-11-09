"""The validate phase binds owner results to the exact declared owner and requests."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from shifter_adapter_sdk import worker
from shifter_adapter_sdk.runtime import PluginManifest, parse_input, parse_result
from shifter_adapter_sdk.validation import ValidationInput

OWNER = "lilrae-opencode-request@1"
MANIFEST = {
    "protocol": "bigrae.runtime-plugin/v2",
    "plugin_id": "example.trial",
    "version": "1.0",
    "distribution": "example-trial",
    "entry_point": "example",
    "worker_image": "registry.example.test/adapters/example@sha256:" + "a" * 64,
    "required_bindings": ["worker"],
    "capabilities": ["guest.configure", "guest.verify", "participant.validate"],
    "participant_validators": [OWNER],
}
RESULT = {"input_digest": "sha256:" + "1" * 64, "normalized": {"values": []}, "contexts": []}


def request():
    return ValidationInput(
        protocol="bigrae.runtime-plugin/v2",
        invocation_id=uuid4(),
        phase="validate",
        manifest=PluginManifest(**MANIFEST),
        owner=OWNER,
        family_digest="sha256:" + "2" * 64,
        requests=[{"participant_address": "agents.red", "participant_manifest": {}, "overrides": []}],
    )


def test_validation_needs_a_declared_owner_on_the_apparatus_protocol():
    for changes in (
        {"participant_validators": []},
        {"capabilities": ["guest.configure", "guest.verify"]},
        {"protocol": "bigrae.runtime-plugin/v1"},
    ):
        with pytest.raises(ValueError):
            PluginManifest(**{**MANIFEST, **changes})
    with pytest.raises(ValueError, match="does not declare"):
        ValidationInput(**{**request().model_dump(mode="json"), "owner": "other@1"})


def test_worker_returns_owner_results_and_the_host_binds_them(monkeypatch):
    sent = request()
    assert parse_input(sent.model_dump_json()) == sent
    plugin = SimpleNamespace(validate=lambda _request: [RESULT])
    monkeypatch.setattr(worker, "_load_plugin", lambda _manifest: plugin)
    result = worker.validate_invocation(sent)
    assert result.status == "validated" and result.results[0].input_digest == RESULT["input_digest"]
    assert parse_result(result.model_dump_json(), sent) == result
    # A wrong count fails closed in the worker; a result for another input fails on the host.
    plugin.validate = lambda _request: [RESULT, RESULT]
    assert worker.validate_invocation(sent).status == "failed"
    with pytest.raises(ValueError, match="does not match"):
        parse_result(json.dumps({**result.model_dump(mode="json"), "input_digest": "sha256:" + "0" * 64}), sent)
