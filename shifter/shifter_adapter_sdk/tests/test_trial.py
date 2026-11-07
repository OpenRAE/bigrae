"""The worker trial-control contract accepts only exact, bounded verb data."""

import json

import pytest
from shifter_adapter_sdk.runtime import PluginManifest
from shifter_adapter_sdk.trial import (
    MAX_TRIAL_OUTPUT_BYTES,
    TrialExport,
    TrialInput,
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
        scenario_sha256="b" * 64,
        pack_sha256="c" * 64,
    )
    assert TrialInput.model_validate_json(value.model_dump_json()) == value
    for field, bad in (("deadline", "2026-11-08T12:00:00+00:00"), ("run_id", "../x"), ("pack_sha256", "C" * 64)):
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
