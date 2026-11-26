"""Authorize qualification from accepted, credential-free provisioner observations."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from engine.models import DisposableWorker, WorkerHostIdentity
from shared.credentials import CredentialContext, resolve_local_credential
from shared.worker_observations import require_fresh_observation

from ._disposable_workers import _audit
from ._worker_custody import _authorized_worker, _lock_worker
from ._worker_qualification_evidence import (
    _NOT_INDEPENDENT,
    WorkerQualification,
    _fingerprint_members,
    _qualification,
)

if TYPE_CHECKING:
    from engine.models import Range

_BINDING_CHANGED = "Worker qualification binding changed"


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

        peers = DisposableWorker.objects.exclude(pk=current.pk)
        fingerprints = result.fingerprints()
        if any(
            peers.filter(**{f"qualification__{kind}_identity": value}).exists()
            or WorkerHostIdentity.objects.filter(kind=kind, value=value).exclude(worker=current).exists()
            for kind, value in fingerprints
        ):
            raise ValueError(_NOT_INDEPENDENT)
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
            raise ValueError(_NOT_INDEPENDENT) from None
        _audit(credential, current, "worker_qualify")


def _require_current_qualification(worker: DisposableWorker, result: WorkerQualification) -> None:
    """Recheck every observation/profile/lifetime condition under the native lock."""
    try:
        current = _qualification(worker)
    except (ValueError, TypeError):
        raise ValueError(_BINDING_CHANGED) from None
    if current != result:
        raise ValueError(_BINDING_CHANGED)
