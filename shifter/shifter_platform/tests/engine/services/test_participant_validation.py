"""Admission runs a backend participant owner only in its declaring installation."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.validation import ValidationResult

from engine.services import _participant_validation as validation

OWNER = "lilrae-opencode-request@1"
MANIFEST = PluginManifest(
    protocol="bigrae.runtime-plugin/v2",
    plugin_id="example.trial",
    version="1.0",
    distribution="example-trial",
    entry_point="example",
    worker_image="registry.example.test/adapters/example@sha256:" + "a" * 64,
    required_bindings=["worker"],
    capabilities=["guest.configure", "guest.verify", "participant.validate"],
    participant_validators=[OWNER],
)
REQUESTS = [{"participant_address": "agents.red", "participant_manifest": {}, "overrides": []}]
RESULT = {"input_digest": "sha256:" + "1" * 64, "normalized": {"values": []}, "contexts": []}


@pytest.fixture
def plugin(monkeypatch):
    """One ready installation and a fake isolated plugin worker."""
    row = SimpleNamespace(
        pk=uuid4(),
        manifest=MANIFEST.model_dump(mode="json"),
        manifest_digest=MANIFEST.digest,
        registry_credentials="",
    )
    rows = [row]
    state = SimpleNamespace(row=row, rows=rows, results=[], launched=[], interrupted=[])

    class _Objects:
        @staticmethod
        def filter(**_kwargs):
            return state.rows

    monkeypatch.setattr("engine.models.RuntimePluginInstallation.objects", _Objects())
    monkeypatch.setattr(validation, "launch_plugin", lambda request, **_: state.launched.append(request))
    monkeypatch.setattr(validation, "interrupt_plugin", state.interrupted.append)
    monkeypatch.setattr("engine.services._runtime_plugin_controller._pull_secret", lambda _row, _request: "")
    monkeypatch.setattr(validation.time, "sleep", lambda _seconds: None)
    return state


def _result(request, status="validated", results=(RESULT,)):
    return ValidationResult(
        protocol="bigrae.runtime-plugin/v2",
        invocation_id=request.invocation_id,
        phase="validate",
        input_digest=request.digest,
        status=status,
        results=list(results),
    )


def test_validated_results_return_in_request_order_after_polling(plugin, monkeypatch):
    def observe(request):
        plugin.results.extend([None, _result(request)])
        return plugin.results.pop(0)

    monkeypatch.setattr(validation, "observe_plugin", observe)
    results = validation.validate_participant_configurations(
        uuid4(), owner=OWNER, family_digest="sha256:" + "2" * 64, requests=REQUESTS
    )

    assert [item.input_digest for item in results] == [RESULT["input_digest"]]
    (request,) = plugin.launched
    assert request.owner == OWNER and request.requests[0].participant_address == "agents.red"


def test_refusal_missing_installation_identity_mismatch_and_timeout_refuse(plugin, monkeypatch):
    def refuse(request):
        return _result(request, status="failed", results=())

    monkeypatch.setattr(validation, "observe_plugin", refuse)
    with pytest.raises(ValueError, match="refused"):
        validation.validate_participant_configurations(
            uuid4(), owner=OWNER, family_digest="sha256:" + "2" * 64, requests=REQUESTS
        )

    with pytest.raises(ValueError, match="Exactly one ready installation"):
        validation.validate_participant_configurations(
            uuid4(), owner="other-owner@1", family_digest="sha256:" + "2" * 64, requests=REQUESTS
        )

    plugin.row.manifest_digest = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        validation.validate_participant_configurations(
            uuid4(), owner=OWNER, family_digest="sha256:" + "2" * 64, requests=REQUESTS
        )
    plugin.row.manifest_digest = MANIFEST.digest

    monkeypatch.setattr(validation, "observe_plugin", lambda _request: None)
    monkeypatch.setattr(validation, "VALIDATION_TIMEOUT_SECONDS", -1)
    with pytest.raises(ValueError, match="timed out"):
        validation.validate_participant_configurations(
            uuid4(), owner=OWNER, family_digest="sha256:" + "2" * 64, requests=REQUESTS
        )
    assert len(plugin.interrupted) == 1
