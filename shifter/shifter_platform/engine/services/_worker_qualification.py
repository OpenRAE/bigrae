"""Synthetic management qualification without an experiment runtime."""

from dataclasses import asdict, dataclass
from ipaddress import ip_address
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from shifter_adapter_sdk.runtime import canonical_digest, decode_message

from shared.credentials import CredentialContext, resolve_local_credential
from shared.disposable_workers import WorkerHostProfile

from ._disposable_workers import _audit, _authorized_worker
from ._range_escape import GuestProbeRequest, run_guest_probe
from ._worker_retirement import _lock_worker

if TYPE_CHECKING:
    from engine.models import Range

_UNAVAILABLE = "Worker management identity is unavailable"

# Fixed input only. Docker always uses this VM's Unix socket, ignoring client
# context/environment. No plugin or inner SDL is needed for qualification.
_PROBE = """import json, pathlib, subprocess
command = ["docker", "--host", "unix:///var/run/docker.sock", "info", "--format", "{{json .}}"]
info = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
daemon = json.loads(info.stdout)
count = subprocess.run(["pgrep", "-xc", "dockerd"], check=True, capture_output=True, text=True, timeout=5)
print(json.dumps({
    "machine_id": pathlib.Path("/etc/machine-id").read_text().strip(),
    "daemon_id": daemon["ID"], "docker_version": daemon["ServerVersion"], "daemon_count": int(count.stdout),
}))
"""


@dataclass(frozen=True, slots=True)
class WorkerQualification:
    """Bounded fingerprints of one qualified VM, machine and Docker daemon."""

    vm_identity: str
    machine_identity: str
    daemon_identity: str
    profile_digest: str


def qualify_disposable_worker(credential: CredentialContext, worker_id: UUID) -> WorkerQualification:
    """Check one accepted guest over pinned private management SSH."""
    from engine.secrets import get_ssh_key

    worker = _authorized_worker(credential, worker_id, "range.access")
    runtime = worker.range
    if runtime.status != "ready" or worker.retirement_at is not None or worker.terminal_at is not None:
        raise ValueError("Worker is not ready for qualification")
    profile = WorkerHostProfile.model_validate(worker.profile)
    if profile.digest != worker.profile_digest:
        raise ValueError("Worker profile identity changed")
    member = _management_member(runtime.provisioned_instances)
    from engine.models import RangeManagementAccess
    from shared.range_management import validate_management_access

    if runtime.provisioner_operation_id is None or runtime.resource_generation is None:
        raise ValueError("Worker management generation is unavailable")
    record = RangeManagementAccess.objects.filter(
        range=runtime, operation_id=runtime.provisioner_operation_id, resource_generation=runtime.resource_generation
    ).first()
    if record is None:
        raise ValueError(_UNAVAILABLE)
    management = validate_management_access(record.bindings).get(member["uuid"])
    if management is None:
        raise ValueError(_UNAVAILABLE)
    generation = (runtime.resource_generation, runtime.provisioner_operation_id)
    output = run_guest_probe(
        GuestProbeRequest(
            host=member["private_ip"],
            username=management["username"],
            port=management["port"],
            private_key=get_ssh_key(management["ssh_key_secret_ref"]),
            host_public_key=management["host_public_key"],
            command="sudo -n python3 -",
            stdin=_PROBE,
            timeout_s=30,
            max_output_bytes=4096,
        )
    )
    result = _qualified_output(output, member, profile)
    _store_qualification(credential, worker_id, runtime, result, generation)
    return result


def _store_qualification(
    credential: CredentialContext,
    worker_id: UUID,
    runtime: Range,
    result: WorkerQualification,
    generation: tuple[UUID, UUID],
) -> None:
    """Fence the observed generation and persist independent identity fingerprints."""
    with transaction.atomic():
        current = _lock_worker(worker_id)
        fresh = current.range
        if (
            resolve_local_credential(credential) != credential
            or (fresh.resource_generation, fresh.provisioner_operation_id) != generation
            or fresh.status != "ready"
            or fresh.provisioned_instances != runtime.provisioned_instances
            or current.retirement_at is not None
        ):
            raise ValueError("Worker qualification binding changed")
        from engine.models import DisposableWorker

        peers = DisposableWorker.objects.exclude(pk=current.pk)
        if (
            peers.filter(qualification__daemon_identity=result.daemon_identity).exists()
            or peers.filter(qualification__machine_identity=result.machine_identity).exists()
        ):
            raise ValueError("Worker identity is not independent")
        current.qualification = asdict(result)
        try:
            with transaction.atomic():
                current.save(update_fields=["qualification"])
        except IntegrityError:
            raise ValueError("Worker identity is not independent") from None
        _audit(credential, current, "worker_qualify")


def _management_member(value: object) -> dict[str, str]:
    """Select the one private GCE guest from accepted native membership."""
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("Worker management membership is unavailable")
    member = value[0]
    if member.get("asset_type") != "gce_vm":
        raise ValueError(_UNAVAILABLE)
    result = _management_strings(member)
    _private_management_address(result["private_ip"])
    return result


def _management_strings(member: dict[str, object]) -> dict[str, str]:
    """Project only bounded identity and transport strings from accepted membership."""
    required = (
        "uuid",
        "private_ip",
        "instance_id",
    )
    result: dict[str, str] = {}
    for field in (*required, "gcp_project_id", "gcp_zone"):
        item = member.get(field, "")
        if not isinstance(item, str):
            raise ValueError(_UNAVAILABLE)
        result[field] = item
    if any(not result[key].strip() for key in required):
        raise ValueError(_UNAVAILABLE)
    return result


def _private_management_address(value: str) -> None:
    """Require a routable private management address without local or link-local aliases."""
    address = ip_address(value)
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError("Worker management address is not private")


def _qualified_output(output: str, member: dict[str, str], profile: WorkerHostProfile) -> WorkerQualification:
    """Validate the fixed probe response and retain only identity fingerprints."""
    try:
        payload = decode_message(output, limit=4096)
        if not isinstance(payload, dict) or set(payload) != {
            "machine_id",
            "daemon_id",
            "docker_version",
            "daemon_count",
        }:
            raise ValueError
        if (
            type(payload["daemon_count"]) is not int
            or payload["daemon_count"] != 1
            or payload["docker_version"] != profile.docker_version
        ):
            raise ValueError
        machine = _guest_identity(payload["machine_id"])
        daemon = _guest_identity(payload["daemon_id"])
        vm = {key: member.get(key, "") for key in ("gcp_project_id", "gcp_zone", "instance_id")}
        return WorkerQualification(
            canonical_digest(vm),
            canonical_digest(machine),
            canonical_digest(daemon),
            profile.digest,
        )
    except (ValueError, KeyError, TypeError):
        raise ValueError("Worker qualification failed") from None


def _guest_identity(value: object) -> str:
    """Reject oversized or executable guest identity data before hashing it."""
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= 128
        or not value.isascii()
        or not all(character.isalnum() or character in "-:" for character in value)
    ):
        raise ValueError("Worker identity is invalid")
    return value
