"""The worker-trial runner starts at most once, stops at the deadline and returns a verified archive."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from shared.worker_trial import WorkerTrialInput

import worker_trial_ops
from executors.base import CommandResult

ARCHIVE = b"sealed synthetic run archive"
STAGED = {"trial.json": b"{}", "scenario.sdl": b"name: synthetic\n", "pack.tar": b"synthetic pack"}


@dataclass
class FakeWorker:
    """A worker whose trial-control verbs answer from a status script."""

    statuses: list[dict]
    commands: list[str] = field(default_factory=list)
    received: dict[str, bytes] = field(default_factory=dict)

    def run_command(self, target, script, *, timeout_seconds, document_name):
        self.commands.append(script)
        return CommandResult(True, 0, "", "")

    def run_command_streaming(self, target, script, *, stdin_path, timeout_seconds, document_name):
        name = script.rsplit("/", 1)[-1]
        with open(stdin_path, "rb") as stream:
            self.received[name] = stream.read()
        return CommandResult(True, 0, "", "")

    def run_command_to_file(self, target, script, *, output_path, max_bytes, timeout_seconds, document_name):
        self.commands.append(script)
        if script.endswith(" status"):
            body = json.dumps({"schema_version": "bigrae.trial-status/v1", **self.statuses.pop(0)}).encode()
        elif script.endswith(" export"):
            body = json.dumps(
                {
                    "schema_version": "bigrae.trial-export/v1",
                    "run_id": "run-1",
                    "attempt_id": "attempt-1",
                    "file": "run-1.tar.gz",
                    "sha256": hashlib.sha256(ARCHIVE).hexdigest(),
                    "size_bytes": len(ARCHIVE),
                }
            ).encode()
        else:
            body = ARCHIVE
        with open(output_path, "wb") as stream:
            stream.write(body[:max_bytes])
        return 0


@dataclass
class FakeStorage:
    uploaded: dict[str, bytes] = field(default_factory=dict)

    def download_object(self, bucket, key, dest_path, *, max_bytes, expected_identity=None):
        with open(dest_path, "wb") as stream:
            stream.write(STAGED[key.rsplit("/", 1)[-1]])
        return {}

    def upload_new_object(self, bucket, key, source_path):
        with open(source_path, "rb") as stream:
            self.uploaded[key] = stream.read()


def status(state, *, sealed=False, exit_code=None):
    value = {"run_id": "run-1", "attempt_id": "attempt-1", "state": state, "sealed": sealed}
    return value if exit_code is None else {**value, "exit_code": exit_code}


def trial_input(*, stop=False, deadline=None):
    return WorkerTrialInput(
        trial_id=uuid4(),
        generation=uuid4(),
        range_request_id=uuid4(),
        provision_operation_id=uuid4(),
        deadline=(deadline or datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        staged={
            name: {"key": f"trial-inputs/a/{name}", "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            for name, raw in STAGED.items()
        },
        stop=stop,
    )


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(worker_trial_ops, "get_object_storage", lambda: fake)
    monkeypatch.setattr(worker_trial_ops, "load_raes_content_delivery_config", lambda: type("C", (), {"bucket": "b"}))
    monkeypatch.setattr(worker_trial_ops, "POLL_SECONDS", 0)
    return fake


def execution(worker):
    return type("Execution", (), {"executor": worker, "target": "10.0.0.2", "document_name": "AWS-RunShellScript"})


def test_run_stages_inputs_starts_once_and_returns_the_verified_archive(storage):
    worker = FakeWorker([status("prepared"), status("running"), status("exited", sealed=True, exit_code=0)])
    value = trial_input()
    receipt = worker_trial_ops.execute_worker_trial(execution(worker), value, "run", "op-1")
    assert worker.received == STAGED
    assert sum("systemd-run" in command for command in worker.commands) == 1
    assert (receipt.state, receipt.exit_code, receipt.sealed) == ("exited", 0, True)
    assert receipt.archive.key == f"trial-exports/{value.trial_id}/op-1/run-1.tar.gz"
    assert storage.uploaded == {receipt.archive.key: ARCHIVE}


def test_run_after_a_lost_result_never_starts_a_second_trial(storage):
    worker = FakeWorker([status("running"), status("exited", exit_code=1)])
    receipt = worker_trial_ops.execute_worker_trial(execution(worker), trial_input(), "run", "op-2")
    assert not any("systemd-run" in command for command in worker.commands)
    assert (receipt.state, receipt.sealed, receipt.archive) == ("exited", False, None)
    assert storage.uploaded == {}


def test_collect_with_stop_stops_a_running_trial_and_never_starts_one(storage):
    worker = FakeWorker([status("running"), status("exited", sealed=True, exit_code=0)])
    worker_trial_ops.execute_worker_trial(execution(worker), trial_input(stop=True), "collect", "op-3")
    assert any(command.endswith(" stop") for command in worker.commands)
    assert not any("systemd-run" in command for command in worker.commands)


def test_the_deadline_forces_a_stop_and_a_changed_archive_is_refused(storage, monkeypatch):
    past = datetime.now(UTC) - timedelta(seconds=worker_trial_ops.DRAIN_SECONDS + 5)
    worker = FakeWorker([status("running"), status("running"), status("exited", sealed=True, exit_code=0)])
    original = worker.run_command_to_file

    def tamper(target, script, **kwargs):
        code = original(target, script, **kwargs)
        if script.startswith("cat "):
            with open(kwargs["output_path"], "ab") as stream:
                stream.write(b"x")
        return code

    worker.run_command_to_file = tamper
    with pytest.raises(worker_trial_ops.WorkerTrialError):
        worker_trial_ops.execute_worker_trial(execution(worker), trial_input(deadline=past), "run", "op-4")
    assert any(command.endswith(" stop") for command in worker.commands)
    assert storage.uploaded == {}


def test_bounded_ssh_copy_refuses_oversized_output(tmp_path):
    from executors.guest_ssh_executor import _invoke_ssh_to_file

    path = os.fspath(tmp_path / "out")
    with pytest.raises(Exception, match="byte"):
        _invoke_ssh_to_file(["sh", "-c", "head -c 4096 /dev/zero"], path, 16, 30)
    assert _invoke_ssh_to_file(["sh", "-c", "printf ok"], path, 16, 30) == 0
