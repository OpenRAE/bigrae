"""The worker-trial runner starts at most once, stops at the deadline and returns a verified archive."""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from shared.worker_trial import WorkerTrialInput
from shifter_adapter_sdk.trial import TrialPeers

import worker_trial_ops
from executors.base import CommandResult

ARCHIVE = b"sealed synthetic run archive"
STAGED = {
    "trial.json": b"{}",
    "trial-unit.json": b'{"plan_entry_id": "e"}',
    "scenario.sdl": b"name: synthetic\n",
}


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
            answer = self.statuses.pop(0)
            if answer.get("fail"):
                return 1
            body = json.dumps({"schema_version": "bigrae.trial-status/v1", **answer}).encode()
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


class ShellPeer:
    """A peer VM whose commands run in a local shell, so the authorized-keys edit runs for real."""

    closed = 0

    def run_command(self, target, script, *, timeout_seconds, document_name):
        script = f"set -euo pipefail\n{script}\n"
        result = subprocess.run(["/bin/bash"], input=script, text=True, capture_output=True, check=False)
        return CommandResult(result.returncode == 0, result.returncode, result.stdout, result.stderr)

    def guest(self):
        peer = self

        class Guest:
            executor, target, document_name = peer, "10.0.0.3", "AWS-RunShellScript"

            @staticmethod
            def close():
                peer.closed += 1

        return Guest


def _peer(shell):
    return worker_trial_ops.PeerVM(
        node="nodes.victim", address="10.0.0.3", host_public_key="ssh-ed25519 AAAAhost root@victim", guest=shell.guest
    )


def test_each_run_gives_the_trial_host_a_new_key_that_only_the_peers_root_authorizes(storage, tmp_path, monkeypatch):
    """#2947: the trial host's root reaches the worker's other VMs as root with a key for this trial only."""
    keys = tmp_path / "ssh" / "authorized_keys"
    keys.parent.mkdir()
    keys.write_text("ssh-ed25519 AAAAoperator operator\n")
    monkeypatch.setattr(worker_trial_ops, "_AUTHORIZED_KEYS", os.fspath(keys))
    monkeypatch.setattr(worker_trial_ops, "_AUTHORIZED_KEYS_DIRECTORY", os.fspath(keys.parent))
    shell = ShellPeer()
    authorized = []
    for attempt in ("op-1", "op-2"):
        worker = FakeWorker([status("prepared"), status("exited", sealed=True, exit_code=0)])
        worker_trial_ops.execute_worker_trial(execution(worker), trial_input(), "run", attempt, [_peer(shell)])
        private = serialization.load_ssh_private_key(worker.received["id_ed25519"], password=None)
        public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        hosts = TrialPeers.model_validate_json(worker.received["hosts.json"])
        assert hosts.peers["nodes.victim"].model_dump(mode="json") == {
            "address": "10.0.0.3",
            "host_public_key": "ssh-ed25519 AAAAhost",
        }
        assert keys.read_text().splitlines() == [
            "ssh-ed25519 AAAAoperator operator",
            f"{public.decode()} bigrae-trial-peer",
        ]
        authorized.append(public)
    assert authorized[0] != authorized[1] and shell.closed == 2


def test_peer_vms_are_named_by_node_address_and_open_their_own_guest():
    output = {"uuid": "nodes.victim#0", "private_ip": "10.0.0.3", "gcp_host_public_key": "ssh-ed25519 AAAAhost"}
    opened = []
    (peer,) = worker_trial_ops.peer_vms([output], lambda value: opened.append(value) or "guest")
    assert (peer.node, peer.address, peer.host_public_key) == ("nodes.victim", "10.0.0.3", "ssh-ed25519 AAAAhost")
    assert peer.guest() == "guest" and opened == [output]


def test_a_one_vm_worker_gets_no_peer_key(storage):
    worker = FakeWorker([status("prepared"), status("exited", sealed=True, exit_code=0)])
    worker_trial_ops.execute_worker_trial(execution(worker), trial_input(), "run", "op-1")
    assert set(worker.received) == set(STAGED)


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


class CommandOnlyWorker:
    """A transport that runs commands but cannot stream input or copy output."""

    def run_command(self, target, script, *, timeout_seconds, document_name):
        raise AssertionError("a refused transport runs no command")


@pytest.mark.parametrize(("operation", "reason"), [("run", "stream trial inputs"), ("collect", "copy trial output")])
def test_a_transport_without_the_bounded_ports_is_refused(storage, operation, reason):
    with pytest.raises(worker_trial_ops.WorkerTrialError, match=reason):
        worker_trial_ops.execute_worker_trial(execution(CommandOnlyWorker()), trial_input(), operation, "op-5")
    assert storage.uploaded == {}


def test_bounded_ssh_copy_refuses_oversized_output(tmp_path):
    from executors._ssh_process import invoke_ssh_to_file

    path = os.fspath(tmp_path / "out")
    with pytest.raises(Exception, match="byte"):
        invoke_ssh_to_file(["sh", "-c", "head -c 4096 /dev/zero"], path, 16, 30)
    assert invoke_ssh_to_file(["sh", "-c", "printf ok"], path, 16, 30) == 0


def test_transient_status_failures_while_running_do_not_end_the_run(storage, monkeypatch):
    monkeypatch.setattr(worker_trial_ops.time, "sleep", lambda _seconds: None)
    failed = {"fail": True}
    worker = FakeWorker(
        [status("prepared"), failed, status("running"), failed, failed, status("exited", sealed=True, exit_code=0)]
    )
    receipt = worker_trial_ops.execute_worker_trial(execution(worker), trial_input(), "run", "op-5")
    assert receipt.sealed and receipt.archive is not None


def test_a_persistent_status_failure_still_ends_the_run(storage, monkeypatch):
    monkeypatch.setattr(worker_trial_ops.time, "sleep", lambda _seconds: None)
    worker = FakeWorker([status("prepared"), *[{"fail": True}] * (worker_trial_ops.STATUS_RETRIES + 1)])
    with pytest.raises(worker_trial_ops.WorkerTrialError):
        worker_trial_ops.execute_worker_trial(execution(worker), trial_input(), "run", "op-6")


def test_the_trial_runs_on_the_named_vm_of_a_multi_vm_worker():
    """#2947: a multi-VM worker names its trial host; a one-VM worker has exactly one VM."""
    from worker_trial_target import trial_instance

    workstation, victim = {"uuid": "provision.node.workstation#0"}, {"uuid": "provision.node.victim#0"}
    assert trial_instance([victim, workstation], "provision.node.workstation") is workstation
    assert trial_instance([victim], "") is victim
    for instances, trial_host in (([victim, workstation], ""), ([victim], "provision.node.workstation")):
        with pytest.raises(ValueError, match="exactly one VM"):
            trial_instance(instances, trial_host)
