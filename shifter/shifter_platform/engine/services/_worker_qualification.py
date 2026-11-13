"""Authorize qualification from accepted, credential-free provisioner observations."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.credentials import CredentialContext, resolve_local_credential
from shared.disposable_workers import WorkerHostProfile
from shared.worker_observations import require_fresh_observation, validate_worker_observations

from ._disposable_workers import _audit, _authorized_worker
from ._worker_retirement import _lock_worker

if TYPE_CHECKING:
    from engine.models import DisposableWorker, Range

_BINDING_CHANGED = "Worker qualification binding changed"


@dataclass(frozen=True, slots=True)
class WorkerQualification:
    """Safe identity facts bound to one accepted generation and apparatus profile."""

    vm_identity: str
    machine_identity: str
    daemon_identity: str
    hardware: dict[str, Any]
    profile_digest: str
    observed_at: str
    operation_id: str
    resource_generation: str
    #: The other VMs of a multi-VM worker, each with its member, fingerprints, hardware and observation time.
    hosts: tuple[dict[str, Any], ...] = ()

    def record(self) -> dict[str, Any]:
        """Return the stored form; a one-VM worker keeps its earlier shape."""
        value = asdict(self)
        value["hosts"] = list(value["hosts"])
        if not value["hosts"]:
            del value["hosts"]
        return value

    def fingerprints(self) -> list[tuple[str, str]]:
        """Return every VM's (kind, fingerprint), the trial host first."""
        hosts = [asdict(self), *self.hosts]
        return [(kind, host[f"{kind}_identity"]) for host in hosts for kind in _KINDS]


_KINDS = ("vm", "machine", "daemon")


def qualify_disposable_worker(credential: CredentialContext, worker_id: UUID) -> WorkerQualification:
    """Validate the current provisioner observation without accessing management keys."""
    worker = _authorized_worker(credential, worker_id, "range.access")
    result = _qualification(worker)
    runtime = worker.range
    if runtime.resource_generation is None or runtime.provisioner_operation_id is None:
        raise ValueError("Worker observation generation is unavailable")
    _store_qualification(
        credential, worker_id, runtime, result, (runtime.resource_generation, runtime.provisioner_operation_id)
    )
    return result


def _qualification(worker: DisposableWorker) -> WorkerQualification:
    """Require the current apparatus and an accepted, fresh observation of every worker VM."""
    runtime = worker.range
    profile = _worker_profile(worker)
    observed = _observed_hosts(runtime, profile)
    hardware, now = profile.hardware, timezone.now()
    for address, host in observed.items():
        require_fresh_observation(host, now)
        if host["docker_version"] != profile.docker_version:
            raise ValueError("Worker runtime version differs from the retained profile")
        if any(host["hardware"][key] != value for key, value in hardware[address].items()):
            raise ValueError("Worker hardware differs from the retained profile")
    trial = observed[profile.trial_host_address]
    hosts = tuple(
        {"member": _member(address), **{key: host[key] for key in _HOST_FACTS}}
        for address, host in sorted(observed.items())
        if address != profile.trial_host_address
    )
    result = WorkerQualification(
        trial["vm_identity"],
        trial["machine_identity"],
        trial["daemon_identity"],
        trial["hardware"],
        profile.digest,
        trial["observed_at"],
        str(runtime.provisioner_operation_id),
        str(runtime.resource_generation),
        hosts,
    )
    fingerprints = result.fingerprints()
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("Worker identity is not independent")
    return result


_HOST_FACTS = ("vm_identity", "machine_identity", "daemon_identity", "hardware", "observed_at")


def _fingerprint_members(worker: DisposableWorker, result: WorkerQualification) -> list[str]:
    """Return the member of each fingerprint, in ``WorkerQualification.fingerprints`` order."""
    trial = _member(WorkerHostProfile.model_validate(worker.profile).trial_host_address)
    return [member for member in (trial, *(host["member"] for host in result.hosts)) for _ in _KINDS]


def _member(address: str) -> str:
    """Return the realized member identifier of a one-instance worker VM."""
    return f"{address}#0"


def _worker_profile(worker: DisposableWorker) -> WorkerHostProfile:
    """Validate immutable apparatus and the worker's qualification lifetime."""
    runtime = worker.range
    if (
        runtime.status != "ready"
        or worker.retirement_at is not None
        or worker.terminal_at is not None
        or worker.deadline <= timezone.now()
    ):
        raise ValueError("Worker is not ready for qualification")
    profile = WorkerHostProfile.model_validate(worker.profile)
    if profile.digest != worker.profile_digest:
        raise ValueError("Worker profile identity changed")
    return profile


def _observed_hosts(runtime: Range, profile: WorkerHostProfile) -> dict[str, dict[str, Any]]:
    """Resolve the exact accepted generation and one GCE member for each worker VM, by node address."""
    from engine.models import WorkerHostObservation

    members = runtime.provisioned_instances
    expected = {_member(node.address): node.address for node in profile.nodes}
    if (
        not isinstance(members, list)
        or not all(isinstance(member, dict) for member in members)
        or sorted(str(member.get("uuid")) for member in members) != sorted(expected)
    ):
        raise ValueError("Worker observation membership is unavailable")
    if runtime.range_backend != "gce" or any(member.get("asset_type") != "gce_vm" for member in members):
        raise ValueError("Worker observation backend is unavailable")
    if runtime.provisioner_operation_id is None or runtime.resource_generation is None:
        raise ValueError("Worker observation generation is unavailable")
    record = WorkerHostObservation.objects.filter(
        range=runtime, operation_id=runtime.provisioner_operation_id, resource_generation=runtime.resource_generation
    ).first()
    if record is None:
        raise ValueError("Worker host observation is unavailable")
    observations = validate_worker_observations(record.observations)
    if set(observations) != set(expected):
        raise ValueError("Worker observation membership changed")
    return {expected[member]: observation for member, observation in observations.items()}


def has_current_qualification(worker: DisposableWorker) -> bool:
    """Historical fingerprints alone never establish a currently qualified worker."""
    if not worker.qualification:
        return False
    try:
        return worker.qualification == _qualification(worker).record()
    except (ValueError, TypeError):
        return False


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
            or fresh.provisioned_instances != runtime.provisioned_instances
        ):
            raise ValueError(_BINDING_CHANGED)
        _require_current_qualification(current, result)
        require_fresh_observation({"observed_at": result.observed_at}, timezone.now())
        from engine.models import DisposableWorker, WorkerHostIdentity

        peers = DisposableWorker.objects.exclude(pk=current.pk)
        fingerprints = result.fingerprints()
        if any(
            peers.filter(**{f"qualification__{kind}_identity": value}).exists()
            or WorkerHostIdentity.objects.filter(kind=kind, value=value).exclude(worker=current).exists()
            for kind, value in fingerprints
        ):
            raise ValueError("Worker identity is not independent")
        current.qualification = result.record()
        try:
            with transaction.atomic():
                current.save(update_fields=["qualification"])
                # Every VM's fingerprints, so a cloned VM cannot qualify even concurrently.
                current.host_identities.all().delete()
                WorkerHostIdentity.objects.bulk_create(
                    WorkerHostIdentity(worker=current, member=member, kind=kind, value=value)
                    for member, (kind, value) in zip(_fingerprint_members(current, result), fingerprints, strict=True)
                )
        except IntegrityError:
            raise ValueError("Worker identity is not independent") from None
        _audit(credential, current, "worker_qualify")


def _require_current_qualification(worker: DisposableWorker, result: WorkerQualification) -> None:
    """Recheck every observation/profile/lifetime condition under the native lock."""
    try:
        current = _qualification(worker)
    except (ValueError, TypeError):
        raise ValueError(_BINDING_CHANGED) from None
    if current != result:
        raise ValueError(_BINDING_CHANGED)
