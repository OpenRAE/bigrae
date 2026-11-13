"""The worker trial-control contract accepts only exact, bounded verb data."""

import json

import pytest
from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.trial import (
    MAX_TRIAL_OUTPUT_BYTES,
    AssignedTrialInput,
    AssignedTrialInputs,
    AssignedTrialSeal,
    TrialExport,
    TrialInput,
    TrialSeal,
    TrialStatus,
    parse_trial_output,
)

_MANIFEST = {
    "plugin_id": "example.trial",
    "version": "1.0",
    "distribution": "example-trial",
    "entry_point": "example",
    "worker_image": "registry.example.test/adapters/example@sha256:" + "a" * 64,
    "required_bindings": ["worker"],
}


def test_trial_control_requires_the_apparatus_protocol_and_configure():
    manifest = PluginManifest(
        protocol="bigrae.runtime-plugin/v2",
        capabilities=["guest.configure", "guest.verify", "trial.control"],
        **_MANIFEST,
    )
    assert "trial.control" in manifest.capabilities
    with pytest.raises(ValueError, match="trial control"):
        PluginManifest(
            protocol="bigrae.runtime-plugin/v1",
            capabilities=["guest.configure", "guest.verify", "trial.control"],
            **_MANIFEST,
        )
    with pytest.raises(ValueError, match="trial control"):
        PluginManifest(
            protocol="bigrae.runtime-plugin/v2",
            capabilities=["guest.verify", "trial.control"],
            **_MANIFEST,
        )


def test_trial_input_binds_identity_deadline_and_digests():
    value = TrialInput(
        run_id="run-1",
        attempt_id="0f0e0d0c-0b0a-4908-8706-050403020100",
        deadline="2026-11-08T12:00:00Z",
        unit_sha256="b" * 64,
        scenario_sha256="c" * 64,
    )
    assert TrialInput.model_validate_json(value.model_dump_json()) == value
    for field, bad in (
        ("deadline", "2026-11-08T12:00:00+00:00"),
        ("run_id", "../x"),
        ("unit_sha256", "B" * 64),
        ("scenario_sha256", "C" * 64),
    ):
        with pytest.raises(ValueError):
            TrialInput.model_validate({**value.model_dump(), field: bad})


def test_status_output_is_consistent_and_bounded():
    running = parse_trial_output(
        b'{"run_id":"run-1","attempt_id":"a-1","state":"running","sealed":false}\n', TrialStatus
    )
    assert running.state == "running" and running.exit_code is None
    exited = parse_trial_output(
        json.dumps(
            {"run_id": "run-1", "attempt_id": "a-1", "state": "exited", "sealed": True, "exit_code": 0}
        ).encode(),
        TrialStatus,
    )
    assert exited.sealed
    for invalid in (
        b'{"run_id":"run-1","attempt_id":"a-1","state":"running","sealed":true}',
        b'{"run_id":"run-1","attempt_id":"a-1","state":"exited","sealed":false}',
        b'{"run_id":"run-1","run_id":"run-2","attempt_id":"a-1","state":"running","sealed":false}',
        b'{"run_id":"run-1","attempt_id":"a-1","state":"running","sealed":false,"extra":1}',
        b"x" * (MAX_TRIAL_OUTPUT_BYTES + 1),
    ):
        with pytest.raises(ValueError):
            parse_trial_output(invalid, TrialStatus)


def test_export_output_names_one_file_without_a_path():
    value = parse_trial_output(
        json.dumps(
            {"run_id": "run-1", "attempt_id": "a-1", "file": "run-1.tar", "sha256": "d" * 64, "size_bytes": 10}
        ).encode(),
        TrialExport,
    )
    assert value.file == "run-1.tar"
    for file in ("../run.tar", "/tmp/run.tar", "sub/run.tar"):
        with pytest.raises(ValueError):
            TrialExport.model_validate({**value.model_dump(), "file": file})


def _seal(**changes):
    member = {
        "path": "manifest.json",
        "size_bytes": 2,
        "checksum": {"algorithm": "sha256", "value": "a" * 64},
        "media_type": "application/json",
        "role": "manifest",
    }
    return {
        "run_id": "run-1",
        "run_version": "1",
        "run_status": "completed",
        "outcome_status": "not-evaluated",
        "run_record_digest": "sha256:" + "a" * 64,
        "completeness": {"complete": True, "limitations": []},
        "inventory": [member],
    } | changes


def test_seal_names_its_owner_and_only_the_raes_run_record_contract():
    seal = TrialSeal.model_validate(_seal())
    dumped = seal.model_dump(mode="json")
    assert dumped["schema_version"] == "bigrae.trial-seal/v1"
    assert dumped["sealed_contract_versions"] == ["experiment-run/v1"]
    for changes in (
        {"sealed_contract_versions": ["lilrae-trial-record/v1"]},
        {"schema_version": "aptl.run-seal/v1"},
        {"completeness": {"complete": True, "limitations": ["capture lost"]}},
        {"completeness": {"complete": False, "limitations": []}},
        {"inventory": []},
        {"run_record_digest": "a" * 64},
    ):
        with pytest.raises(ValueError):
            TrialSeal.model_validate(_seal(**changes))


def test_an_apparatus_serves_one_trial_mode():
    manifest = PluginManifest(
        protocol="bigrae.runtime-plugin/v2",
        capabilities=["guest.configure", "guest.verify", "trial.assigned"],
        **_MANIFEST,
    )
    assert "trial.assigned" in manifest.capabilities
    for capabilities in (
        ["guest.configure", "guest.verify", "trial.control", "trial.assigned"],
        ["guest.verify", "trial.assigned"],
    ):
        with pytest.raises(ValueError, match="one trial mode"):
            PluginManifest(protocol="bigrae.runtime-plugin/v2", capabilities=capabilities, **_MANIFEST)


def _inputs(**changes):
    entry = {"name": "worker", "version": "1", "schema_version": "backend-manifest/v2", "manifest": {}}
    return {
        "family_digest": "sha256:" + "1" * 64,
        "experiment": {},
        "task": {},
        "capture_specs": {},
        "apparatus_manifests": [entry | {"kind": "backend"}, entry | {"kind": "processor", "name": "processor"}],
        "realization_envelope": {},
        "backend": "worker",
    } | changes


def test_assigned_trial_inputs_name_exactly_one_selected_backend():
    assert AssignedTrialInputs.model_validate(_inputs()).backend == "worker"
    with pytest.raises(ValueError, match="selected backend"):
        AssignedTrialInputs.model_validate(_inputs(backend="other"))
    staged = AssignedTrialInput(
        run_id="run-1", attempt_id="attempt-1", deadline="2026-11-13T20:00:00Z",
        assignment_sha256="a" * 64, inputs_sha256="b" * 64,
    )
    assert staged.schema_version == "bigrae.assigned-trial-input/v1"
    with pytest.raises(ValueError, match="UTC"):
        AssignedTrialInput.model_validate(staged.model_dump() | {"deadline": "2026-11-13T20:00:00+01:00"})


def _member(path, value):
    return {"path": path, "size_bytes": 2, "checksum": {"value": value}, "media_type": "application/json", "role": "x"}


def test_assigned_trial_seal_binds_the_outcome_bytes():
    seal = {"run_id": "run-1", "attempt_id": "attempt-1", "outcome_digest": "sha256:" + "c" * 64}
    assert AssignedTrialSeal.model_validate(seal | {"inventory": [_member("outcome.json", "c" * 64)]})
    for inventory in (
        [_member("outcome.json", "d" * 64)],
        [_member("evidence/a.json", "c" * 64)],
        [_member("outcome.json", "c" * 64), _member("outcome.json", "c" * 64)],
    ):
        with pytest.raises(ValueError):
            AssignedTrialSeal.model_validate(seal | {"inventory": inventory})
