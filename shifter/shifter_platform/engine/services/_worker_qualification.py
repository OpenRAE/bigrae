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
    """Require the current apparatus and accepted, fresh host observation."""
    runtime = worker.range
    profile = _worker_profile(worker)
    observed = _observed_host(runtime)
    require_fresh_observation(observed, timezone.now())
    if observed["docker_version"] != profile.docker_version:
        raise ValueError("Worker runtime version differs from the retained profile")
    if any(observed["hardware"][key] != value for key, value in profile.hardware.items()):
        raise ValueError("Worker hardware differs from the retained profile")
    return WorkerQualification(
        observed["vm_identity"],
        observed["machine_identity"],
        observed["daemon_identity"],
        observed["hardware"],
        profile.digest,
        observed["observed_at"],
        str(runtime.provisioner_operation_id),
        str(runtime.resource_generation),
    )


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


def _observed_host(runtime: Range) -> dict[str, Any]:
    """Resolve only the exact accepted generation and its single GCE member."""
    from engine.models import WorkerHostObservation

    members = runtime.provisioned_instances
    if not isinstance(members, list) or len(members) != 1 or not isinstance(members[0], dict):
        raise ValueError("Worker observation membership is unavailable")
    if runtime.range_backend != "gce" or members[0].get("asset_type") != "gce_vm":
        raise ValueError("Worker observation backend is unavailable")
    if runtime.provisioner_operation_id is None or runtime.resource_generation is None:
        raise ValueError("Worker observation generation is unavailable")
    record = WorkerHostObservation.objects.filter(
        range=runtime, operation_id=runtime.provisioner_operation_id, resource_generation=runtime.resource_generation
    ).first()
    if record is None:
        raise ValueError("Worker host observation is unavailable")
    observations = validate_worker_observations(record.observations)
    if set(observations) != {members[0].get("uuid")}:
        raise ValueError("Worker observation membership changed")
    return next(iter(observations.values()))


def has_current_qualification(worker: DisposableWorker) -> bool:
    """Historical fingerprints alone never establish a currently qualified worker."""
    if not worker.qualification:
        return False
    try:
        return worker.qualification == asdict(_qualification(worker))
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
        from engine.models import DisposableWorker

        peers = DisposableWorker.objects.exclude(pk=current.pk)
        if (
            peers.filter(qualification__vm_identity=result.vm_identity).exists()
            or peers.filter(qualification__daemon_identity=result.daemon_identity).exists()
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


def _require_current_qualification(worker: DisposableWorker, result: WorkerQualification) -> None:
    """Recheck every observation/profile/lifetime condition under the native lock."""
    try:
        current = _qualification(worker)
    except (ValueError, TypeError):
        raise ValueError(_BINDING_CHANGED) from None
    if current != result:
        raise ValueError(_BINDING_CHANGED)
