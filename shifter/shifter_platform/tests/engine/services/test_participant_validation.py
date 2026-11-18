"""Admission runs a backend participant owner only in its declaring installation.

Admission records the validate request; the plugin launcher runs the isolated
worker and records its authorized result.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone
from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.validation import ValidationInput, ValidationResult

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
FAMILY = "sha256:" + "2" * 64


def _result(request, status="validated", results=(RESULT,)):
    return ValidationResult(
        protocol="bigrae.runtime-plugin/v2",
        invocation_id=request.invocation_id,
        phase="validate",
        input_digest=request.digest,
        status=status,
        results=list(results),
    )


@pytest.fixture
def installation(monkeypatch):
    """One ready installation and a recorded-request store without a database."""
    row = SimpleNamespace(
        pk=uuid4(),
        manifest=MANIFEST.model_dump(mode="json"),
        manifest_digest=MANIFEST.digest,
        registry_credentials="",
    )
    state = SimpleNamespace(row=row, rows=[row], created=[], transitions=[])

    class _Installations:
        @staticmethod
        def filter(**_kwargs):
            return state.rows

    class _Validations:
        @staticmethod
        def create(**fields):
            record = SimpleNamespace(**fields, state="pending", result=None)

            def refresh_from_db(fields=None):
                if state.transitions:
                    record.state, record.result = state.transitions.pop(0)(record)

            record.refresh_from_db = refresh_from_db
            state.created.append(record)
            return record

    monkeypatch.setattr("engine.models.RuntimePluginInstallation.objects", _Installations())
    monkeypatch.setattr("engine.models.RuntimePluginValidation.objects", _Validations())
    monkeypatch.setattr(validation.time, "sleep", lambda _seconds: None)
    return state


def test_admission_records_the_request_and_returns_the_launcher_result(installation):
    def validated(record):
        request = ValidationInput.model_validate(record.input)
        return "validated", _result(request).model_dump(mode="json")

    installation.transitions = [lambda _record: ("pending", None), validated]
    results = validation.validate_participant_configurations(
        uuid4(), owner=OWNER, family_digest=FAMILY, requests=REQUESTS
    )

    assert [item.input_digest for item in results] == [RESULT["input_digest"]]
    (record,) = installation.created
    assert record.installation is installation.row
    assert record.input["owner"] == OWNER and record.input["requests"][0]["participant_address"] == "agents.red"


def test_admission_refuses_a_refusal_a_missing_installation_a_changed_identity_and_a_timeout(installation, monkeypatch):
    installation.transitions = [lambda _record: ("failed", None)]
    with pytest.raises(ValueError, match="refused"):
        validation.validate_participant_configurations(uuid4(), owner=OWNER, family_digest=FAMILY, requests=REQUESTS)

    with pytest.raises(ValueError, match="Exactly one ready installation"):
        validation.validate_participant_configurations(
            uuid4(), owner="other-owner@1", family_digest=FAMILY, requests=REQUESTS
        )

    installation.row.manifest_digest = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        validation.validate_participant_configurations(uuid4(), owner=OWNER, family_digest=FAMILY, requests=REQUESTS)
    installation.row.manifest_digest = MANIFEST.digest

    monkeypatch.setattr(validation, "VALIDATION_TIMEOUT_SECONDS", -60)
    with pytest.raises(ValueError, match="timed out"):
        validation.validate_participant_configurations(uuid4(), owner=OWNER, family_digest=FAMILY, requests=REQUESTS)


@pytest.fixture
def launcher(monkeypatch):
    """Pending recorded requests and a fake isolated plugin worker."""
    installation_row = SimpleNamespace(pk=uuid4(), registry_credentials="")
    request = validation._request(
        SimpleNamespace(manifest=MANIFEST.model_dump(mode="json"), manifest_digest=MANIFEST.digest),
        OWNER,
        FAMILY,
        REQUESTS,
    )
    state = SimpleNamespace(observed=[], launched=[], interrupted=[], updates=[], rows=[])

    def pending_row(expires_in=timedelta(minutes=5)):
        return SimpleNamespace(
            pk=request.invocation_id,
            installation=installation_row,
            input=request.model_dump(mode="json"),
            expires_at=timezone.now() + expires_in,
        )

    class _Query(list):
        def order_by(self, *_fields):
            return self

        def update(self, **fields):
            state.updates.append(fields)
            return 1

    class _Validations:
        @staticmethod
        def filter(**kwargs):
            return _Query(state.rows if kwargs.get("state") == "pending" and "pk" not in kwargs else [None])

    monkeypatch.setattr("engine.models.RuntimePluginValidation.objects", _Validations())
    monkeypatch.setattr(validation, "launch_plugin", lambda item, **_: state.launched.append(item))
    monkeypatch.setattr(validation, "interrupt_plugin", state.interrupted.append)
    monkeypatch.setattr("engine.services._runtime_plugin_controller._pull_secret", lambda _row, _request: "")
    monkeypatch.setattr(validation, "observe_plugin", lambda _request: state.observed.pop(0))
    state.request, state.pending_row = request, pending_row
    return state


def test_launcher_records_only_an_authorized_result_and_keeps_waiting_otherwise(launcher):
    launcher.rows = [launcher.pending_row()]
    launcher.observed = [None, _result(launcher.request)]

    assert validation.reconcile_participant_validations(limit=3) == 1
    assert launcher.updates == []
    validation.reconcile_participant_validations(limit=3)

    (update,) = launcher.updates
    assert update["state"] == "validated"
    assert update["result"]["invocation_id"] == str(launcher.request.invocation_id)
    assert len(launcher.launched) == 2


def test_launcher_fails_an_expired_or_unauthorized_request_and_interrupts_its_worker(launcher):
    launcher.rows = [launcher.pending_row(expires_in=timedelta(seconds=-1))]
    validation.reconcile_participant_validations(limit=3)
    assert launcher.updates[-1] == {"state": "failed", "result": None, "updated_at": launcher.updates[-1]["updated_at"]}

    other = launcher.request.model_copy(update={"invocation_id": uuid4()})
    launcher.rows = [launcher.pending_row()]
    launcher.observed = [_result(other)]
    validation.reconcile_participant_validations(limit=3)
    assert launcher.updates[-1]["state"] == "failed"
    assert len(launcher.interrupted) == 2

    with pytest.raises(ValueError, match="batch size"):
        validation.reconcile_participant_validations(limit=0)
