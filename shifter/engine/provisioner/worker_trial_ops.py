"""Native ``worker-trial`` operations: drive one adapter trial on a disposable worker.

``run`` grants a multi-VM worker's trial host root SSH to its other VMs with a
new key, stages the inputs, starts the adapter's fixed trial-control command when
the worker reports ``prepared``, waits for the trial to end, and returns its
sealed archive. ``collect`` never starts a trial. Worker output is untrusted
data; it selects no command, path or destination.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from shared.worker_trial import (
    MAX_STAGED_BYTES,
    TRIAL_EXPORT_PREFIX,
    ArchiveObject,
    StagedObject,
    WorkerTrialInput,
    WorkerTrialReceipt,
    parse_worker_trial_input,
)
from shifter_adapter_sdk.trial import (
    MAX_TRIAL_ARCHIVE_BYTES,
    MAX_TRIAL_OUTPUT_BYTES,
    TRIAL_CONTROL_COMMAND,
    TRIAL_EXPORT_DIRECTORY,
    TRIAL_INPUT_DIRECTORY,
    TRIAL_PEER_DIRECTORY,
    TRIAL_PEER_HOSTS_FILE,
    TRIAL_PEER_KEY_FILE,
    TrialExport,
    TrialPeer,
    TrialPeers,
    TrialStatus,
    parse_trial_output,
)

from cloud import get_object_storage
from config import load_raes_content_delivery_config
from executors.base import ExecutorConnectionError, FileOutputCommandExecutor, StreamingCommandExecutor
from raes_content_payload import sha256_file

if TYPE_CHECKING:
    from cloud.types import ObjectStorage
    from executors.factory import GuestExecutionContext

logger = logging.getLogger(__name__)

POLL_SECONDS = 30
#: Time after the trial deadline for the adapter to stop participants and seal.
DRAIN_SECONDS = 900
_VERB_TIMEOUT_SECONDS = 120
#: Consecutive failed status polls tolerated while a trial runs. A worker under
#: end-of-trial load can fail one poll; that must not end the operation.
STATUS_RETRIES = 5
_TRANSFER_TIMEOUT_SECONDS = 1800
_UNIT = "bigrae-trial"
#: Comment on the one root authorized key that each trial replaces.
_PEER_KEY_COMMENT = "bigrae-trial-peer"
_AUTHORIZED_KEYS_DIRECTORY = "/root/.ssh"
_AUTHORIZED_KEYS = _AUTHORIZED_KEYS_DIRECTORY + "/authorized_keys"


class WorkerTrialError(RuntimeError):
    """A refused or failed worker trial step; never carries guest output."""


def _file_output(execution: GuestExecutionContext) -> FileOutputCommandExecutor:
    """Return the transport that copies bounded output, or refuse the trial."""
    if not isinstance(execution.executor, FileOutputCommandExecutor):
        raise WorkerTrialError("the worker transport cannot copy trial output")
    return execution.executor


def _streaming(execution: GuestExecutionContext) -> StreamingCommandExecutor:
    """Return the transport that streams a local file to stdin, or refuse the trial."""
    if not isinstance(execution.executor, StreamingCommandExecutor):
        raise WorkerTrialError("the worker transport cannot stream trial inputs")
    return execution.executor


def _verb_output(execution: GuestExecutionContext, verb: str, workdir: str) -> bytes:
    """Run one read-only verb and return its bounded standard output."""
    path = os.path.join(workdir, f"{verb}.json")
    code = _file_output(execution).run_command_to_file(
        execution.target,
        f"{TRIAL_CONTROL_COMMAND} {verb}",
        output_path=path,
        max_bytes=MAX_TRIAL_OUTPUT_BYTES,
        timeout_seconds=_VERB_TIMEOUT_SECONDS,
        document_name=execution.document_name,
    )
    if code != 0:
        raise WorkerTrialError(f"trial {verb} failed")
    with open(path, "rb") as stream:
        return stream.read()


def _run(execution: GuestExecutionContext, command: str) -> None:
    """Run one trial-control command and refuse a failed exit."""
    result = execution.executor.run_command(
        execution.target, command, timeout_seconds=_VERB_TIMEOUT_SECONDS, document_name=execution.document_name
    )
    if not result.success:
        raise WorkerTrialError("worker command failed")


def trial_status(execution: GuestExecutionContext, value: WorkerTrialInput, workdir: str) -> TrialStatus:
    """Return the adapter's status for this exact trial."""
    # Intake binds the archive to the expected run and attempt identities.
    del value
    return parse_trial_output(_verb_output(execution, "status", workdir), TrialStatus)


def _download_staged(storage: ObjectStorage, bucket: str, item: StagedObject, path: str) -> None:
    """Download one staged object and verify its exact digest and size."""
    storage.download_object(bucket, item.key, path, max_bytes=MAX_STAGED_BYTES)
    if os.path.getsize(path) != item.size_bytes or sha256_file(path) != item.sha256:
        raise WorkerTrialError("a staged object differs from its digest")


def stage_inputs(
    execution: GuestExecutionContext, value: WorkerTrialInput, storage: ObjectStorage, bucket: str
) -> None:
    """Copy each staged file to the worker's fixed trial input directory."""
    with tempfile.TemporaryDirectory(prefix="worker-trial-") as staging:
        for name, item in value.staged.items():
            local = os.path.join(staging, name)
            _download_staged(storage, bucket, item, local)
            target = f"{TRIAL_INPUT_DIRECTORY}/{name}"
            result = _streaming(execution).run_command_streaming(
                execution.target,
                f"install -d -m 0700 {TRIAL_INPUT_DIRECTORY} && cat > {target}.part && mv {target}.part {target}",
                stdin_path=local,
                timeout_seconds=_TRANSFER_TIMEOUT_SECONDS,
                document_name=execution.document_name,
            )
            if not result.success:
                raise WorkerTrialError("staging a trial input failed")


@dataclass(frozen=True)
class PeerVM:
    """Another VM of a multi-VM worker: its node address, its pinned host identity, and its guest context."""

    node: str
    address: str
    host_public_key: str
    guest: Callable[[], GuestExecutionContext]


def peer_vms(
    outputs: Sequence[dict[str, object]], guest: Callable[[dict[str, object]], GuestExecutionContext]
) -> list[PeerVM]:
    """Name each other worker VM by its node address, from its management output."""
    return [
        PeerVM(
            node=str(output["uuid"]).rsplit("#", 1)[0],
            address=str(output["private_ip"]),
            host_public_key=str(output["gcp_host_public_key"]),
            guest=lambda output=output: guest(output),
        )
        for output in outputs
    ]


def _stream_file(execution: GuestExecutionContext, local: str, target: str) -> None:
    """Write one root-only file on the guest from a local file, then move it into place."""
    result = _streaming(execution).run_command_streaming(
        execution.target,
        f"umask 077 && install -d -m 0700 {os.path.dirname(target)} && "
        f"cat > {target}.part && mv {target}.part {target}",
        stdin_path=local,
        timeout_seconds=_TRANSFER_TIMEOUT_SECONDS,
        document_name=execution.document_name,
    )
    if not result.success:
        raise WorkerTrialError("writing a trial file failed")


def _authorize(peer: PeerVM, public_key: str) -> None:
    """Replace the peer root's trial key with this trial's public key."""
    line = f"{public_key} {_PEER_KEY_COMMENT}"
    script = (
        f"umask 077 && install -d -m 0700 {_AUTHORIZED_KEYS_DIRECTORY} && touch {_AUTHORIZED_KEYS} && "
        f"{{ grep -v ' {_PEER_KEY_COMMENT}$' {_AUTHORIZED_KEYS} || true; echo '{line}'; }} "
        f"> {_AUTHORIZED_KEYS}.part && "
        f"mv {_AUTHORIZED_KEYS}.part {_AUTHORIZED_KEYS}"
    )
    execution = peer.guest()
    try:
        _run(execution, script)
    finally:
        execution.close()


def grant_peer_access(execution: GuestExecutionContext, peers: Sequence[PeerVM]) -> None:
    """Give the trial host's root a new key that every other worker VM's root authorizes."""
    if not peers:
        return
    hosts = TrialPeers(
        peers={
            peer.node: TrialPeer(address=peer.address, host_public_key=" ".join(peer.host_public_key.split()[:2]))
            for peer in peers
        }
    )
    key = ed25519.Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    for peer in peers:
        _authorize(peer, public_key.decode())
    with tempfile.TemporaryDirectory(prefix="worker-trial-peers-") as workdir:
        private = os.path.join(workdir, TRIAL_PEER_KEY_FILE)
        with open(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(
                key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
                )
            )
        listing = os.path.join(workdir, TRIAL_PEER_HOSTS_FILE)
        with open(listing, "w", encoding="utf-8") as stream:
            stream.write(hosts.model_dump_json())
        _stream_file(execution, private, f"{TRIAL_PEER_DIRECTORY}/{TRIAL_PEER_KEY_FILE}")
        _stream_file(execution, listing, f"{TRIAL_PEER_DIRECTORY}/{TRIAL_PEER_HOSTS_FILE}")


def wait_for_exit(execution: GuestExecutionContext, value: WorkerTrialInput, workdir: str) -> TrialStatus:
    """Poll until the trial exits; stop it once the deadline and drain time pass."""
    deadline = datetime.fromisoformat(value.deadline.replace("Z", "+00:00")) + timedelta(seconds=DRAIN_SECONDS)
    stopped = False
    failures = 0
    while True:
        try:
            status = trial_status(execution, value, workdir)
        except (WorkerTrialError, ExecutorConnectionError, TimeoutError):
            failures += 1
            if failures > STATUS_RETRIES:
                raise
            logger.warning("Worker trial status poll failed; retrying (%d of %d)", failures, STATUS_RETRIES)
            time.sleep(POLL_SECONDS)
            continue
        failures = 0
        if status.state == "exited":
            return status
        if datetime.now(UTC) > deadline and not stopped:
            _run(execution, f"{TRIAL_CONTROL_COMMAND} stop")
            stopped = True
        elif datetime.now(UTC) > deadline + timedelta(seconds=DRAIN_SECONDS):
            raise WorkerTrialError("the trial did not exit after a stop request")
        time.sleep(POLL_SECONDS)


def export_archive(
    execution: GuestExecutionContext, value: WorkerTrialInput, operation_id: str, storage: ObjectStorage, bucket: str
) -> ArchiveObject:
    """Export the sealed run, copy it here, verify it, and create its object."""
    with tempfile.TemporaryDirectory(prefix="worker-trial-export-") as workdir:
        export = parse_trial_output(_verb_output(execution, "export", workdir), TrialExport)
        local = os.path.join(workdir, "archive")
        code = _file_output(execution).run_command_to_file(
            execution.target,
            f"cat {TRIAL_EXPORT_DIRECTORY}/{export.file}",
            output_path=local,
            max_bytes=min(export.size_bytes, MAX_TRIAL_ARCHIVE_BYTES),
            timeout_seconds=_TRANSFER_TIMEOUT_SECONDS,
            document_name=execution.document_name,
        )
        if code != 0 or os.path.getsize(local) != export.size_bytes or sha256_file(local) != export.sha256:
            raise WorkerTrialError("the copied archive differs from its export report")
        key = f"{TRIAL_EXPORT_PREFIX}{value.trial_id}/{operation_id}/{export.file}"
        storage.upload_new_object(bucket, key, local)
        return ArchiveObject(key=key, sha256=export.sha256, size_bytes=export.size_bytes)


def execute_worker_trial(
    execution: GuestExecutionContext,
    value: WorkerTrialInput,
    operation: str,
    operation_id: str,
    peers: Sequence[PeerVM] = (),
) -> WorkerTrialReceipt:
    """Run or collect one trial and return its closed receipt."""
    storage, bucket = get_object_storage(), load_raes_content_delivery_config().bucket
    with tempfile.TemporaryDirectory(prefix="worker-trial-status-") as workdir:
        if operation == "run":
            grant_peer_access(execution, peers)
            stage_inputs(execution, value, storage, bucket)
            if trial_status(execution, value, workdir).state == "prepared":
                _run(execution, f"systemd-run --unit={_UNIT} --collect {TRIAL_CONTROL_COMMAND} start")
            status = wait_for_exit(execution, value, workdir)
        elif value.stop:
            if trial_status(execution, value, workdir).state == "running":
                _run(execution, f"{TRIAL_CONTROL_COMMAND} stop")
            status = wait_for_exit(execution, value, workdir)
        else:
            status = trial_status(execution, value, workdir)
    archive = export_archive(execution, value, operation_id, storage, bucket) if status.sealed else None
    return WorkerTrialReceipt(
        trial_id=value.trial_id, state=status.state, exit_code=status.exit_code, sealed=status.sealed, archive=archive
    )


def run_worker_trial_operation(request_id: str, trial_id: str, operation: str, operation_id: str) -> None:
    """Load the immutable input, run the operation and append its terminal result."""
    from provisioner_db_appends import OperationRef, append_operation_step_result
    from provisioner_db_operation_input import get_operation_input
    from worker_trial_target import peer_guest, worker_guests

    validated = get_operation_input(
        operation_id=operation_id, request_id=request_id, resource="worker-trial", operation=operation
    )
    value = parse_worker_trial_input(validated.payload)
    if str(value.trial_id) != trial_id or str(value.generation) != validated.request_id:
        raise WorkerTrialError("worker trial identity unavailable")
    ref = OperationRef(validated.request_id, validated.operation_id)
    execution = None
    try:
        execution, outputs = worker_guests(value)
        receipt = execute_worker_trial(
            execution, value, operation, validated.operation_id, peer_vms(outputs, peer_guest)
        )
    except Exception as exc:  # noqa: BLE001  # guest boundary: causes can carry guest output; authored failure only
        logger.error(
            "Worker trial %s failed for trial_id=%s exc_type=%s",
            operation,
            trial_id,
            type(exc).__name__,
            exc_info=False,
        )
        append_operation_step_result(
            ref,
            resource="worker-trial",
            operation=operation,
            step="worker_trial_failed",
            result_payload={"reason_code": "cloud_operation_failed", "diagnostic": "Worker trial operation failed"},
        )
        raise WorkerTrialError("worker trial operation failed") from None
    finally:
        if execution is not None:
            execution.close()
    append_operation_step_result(
        ref,
        resource="worker-trial",
        operation=operation,
        step="worker_trial_observed",
        result_payload=receipt.model_dump(mode="json"),
    )
