"""Caller holds and bounded retirement through native cancellation and cleanup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from shared.credentials import CredentialContext, resolve_local_credential

from ._disposable_workers import WorkerView, _audit, _authorized_worker, _installation_authority, _view

if TYPE_CHECKING:
    from engine.models import DisposableWorker, WorkerRetirementHold

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerHoldView:
    hold_id: UUID
    worker_id: UUID
    owner_principal_uuid: UUID
    review_at: datetime
    released: bool
    reason: str


def _lock_worker(worker_id: UUID) -> DisposableWorker:
    from engine.models import DisposableWorker, Range

    native_id = DisposableWorker.objects.values_list("range_id", flat=True).get(pk=worker_id)
    runtime = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=native_id)
    worker = DisposableWorker.objects.select_for_update().get(pk=worker_id, range=runtime)
    worker.range = runtime
    return worker


def acquire_worker_hold(credential: CredentialContext, worker_id: UUID, *, reason: str) -> WorkerHoldView:
    """Hold a generation until its caller explicitly releases evidence custody."""
    from engine.models import WorkerRetirementHold

    _authorized_worker(credential, worker_id, "range.manage")
    if reason not in {"evidence", "capture", "operator"}:
        raise ValueError("Worker hold reason is invalid")
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        if resolve_local_credential(credential) != credential:
            raise ValueError("Worker hold authority changed")
        if (
            worker.retirement_at is not None
            or worker.terminal_at is not None
            or worker.range.status in {"destroying", "destroyed"}
        ):
            raise ValueError("Worker retirement already admitted")
        if worker.range.status != "ready":
            raise ValueError("Worker must be ready before evidence retention")
        active = WorkerRetirementHold.objects.filter(worker=worker, released_at__isnull=True)
        existing = active.filter(owner_principal_uuid=credential.principal.uuid).first()
        if existing is not None:
            return _hold_view(existing)
        if active.count() >= 32:
            raise ValueError("Worker hold limit reached")
        hold = WorkerRetirementHold.objects.create(
            worker=worker,
            owner_principal_uuid=credential.principal.uuid,
            reason=reason,
            review_at=timezone.now() + timedelta(seconds=worker.hold_review_seconds),
        )
        _audit(credential, worker, "worker_hold_acquire", {"hold_id": str(hold.pk), "reason": reason})
        return _hold_view(hold)


def release_worker_hold(
    credential: CredentialContext, hold_id: UUID, *, operator_override: bool = False
) -> WorkerHoldView:
    """Only a hold owner or an explicitly authorized installation operator releases it."""
    from engine.models import WorkerRetirementHold

    hold = WorkerRetirementHold.objects.get(pk=hold_id)
    if operator_override:
        _installation_authority(credential)
    else:
        _authorized_worker(credential, hold.worker_id, "range.manage")
        if hold.owner_principal_uuid != credential.principal.uuid:
            raise PermissionError("Worker hold belongs to another caller")
    with transaction.atomic():
        worker = _lock_worker(hold.worker_id)
        if resolve_local_credential(credential) != credential:
            raise ValueError("Worker hold authority changed")
        hold = WorkerRetirementHold.objects.select_for_update().get(pk=hold_id, worker=worker)
        if hold.released_at is None:
            hold.released_at = timezone.now()
            hold.save(update_fields=["released_at"])
            _audit(
                credential,
                worker,
                "worker_hold_override" if operator_override else "worker_hold_release",
                {"hold_id": str(hold.pk)},
            )
        return _hold_view(hold)


def _hold_view(hold: WorkerRetirementHold) -> WorkerHoldView:
    return WorkerHoldView(
        hold.pk, hold.worker_id, hold.owner_principal_uuid, hold.review_at, hold.released_at is not None, hold.reason
    )


def list_worker_holds(credential: CredentialContext, worker_id: UUID) -> tuple[WorkerHoldView, ...]:
    worker = _authorized_worker(credential, worker_id, "range.read")
    return tuple(_hold_view(hold) for hold in worker.holds.filter(released_at__isnull=True).order_by("created_at")[:32])


def retire_disposable_worker(credential: CredentialContext, worker_id: UUID) -> WorkerView:
    """Retain capacity and ownership while native cleanup converges."""
    from engine.worker_retention import fence_worker_retirement

    _authorized_worker(credential, worker_id, "range.manage")
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        if resolve_local_credential(credential) != credential:
            raise ValueError("Worker retirement authority changed")
        fence_worker_retirement(worker.range, admit=True)
        worker.refresh_from_db()
        _audit(credential, worker, "worker_retire")
        _advance_retirement(worker, timezone.now())
        return _view(worker)


def resume_worker_cleanup(credential: CredentialContext, worker_id: UUID) -> WorkerView:
    """An operator resumes bounded cleanup after separately releasing each hold."""
    from engine.worker_retention import fence_worker_retirement

    _installation_authority(credential)
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        if resolve_local_credential(credential) != credential:
            raise ValueError("Worker recovery authority changed")
        fence_worker_retirement(worker.range, admit=True)
        worker.refresh_from_db()
        worker.recovery_required = False
        worker.recovery_reason = ""
        worker.recovery_attempts = 0
        worker.save(update_fields=["recovery_required", "recovery_attempts", "recovery_reason"])
        _audit(credential, worker, "worker_recover")
        _advance_retirement(worker, timezone.now())
        return _view(worker)


def reconcile_disposable_workers(
    *,
    now: datetime | None = None,
    limit: int = 50,
    worker_ids: tuple[UUID, ...] | None = None,
    credential: CredentialContext | None = None,
) -> int:
    """One bounded pass; expired holds escalate without silently releasing them."""
    from engine.models import DisposableWorker
    from engine.worker_retention import fence_worker_retirement

    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Worker reconciliation limit is invalid")
    if credential is not None:
        _installation_authority(credential)
    if worker_ids is not None and (len(worker_ids) > 100 or any(not isinstance(value, UUID) for value in worker_ids)):
        raise ValueError("Worker reconciliation selection is invalid")
    moment = now or timezone.now()
    rows = DisposableWorker.objects.all()
    if worker_ids is not None:
        rows = rows.filter(pk__in=worker_ids)
    identifiers = list(
        rows.filter(terminal_at__isnull=True)
        .filter(Q(recovery_required=False) | Q(range__status="destroyed"))
        .filter(
            Q(range__status="destroyed")
            | Q(next_recovery_at__lte=moment)
            | Q(holds__released_at__isnull=True, holds__review_at__lte=moment)
        )
        .order_by("next_recovery_at", "id")
        .values_list("id", flat=True)
        .distinct()[:limit]
    )
    for identifier in identifiers:
        with transaction.atomic():
            worker = _lock_worker(identifier)
            if worker.terminal_at is not None:
                continue
            holds = worker.holds.filter(released_at__isnull=True)
            if holds.exists():
                if holds.filter(review_at__lte=moment).exists():
                    worker.recovery_required = True
                    worker.recovery_reason = "hold-review-overdue"
                    worker.save(update_fields=["recovery_required", "recovery_reason"])
                continue
            if worker.retirement_at is None and worker.deadline > moment:
                continue
            fence_worker_retirement(worker.range, admit=True)
            worker.refresh_from_db()
            _advance_retirement(worker, moment)
    return len(identifiers)


def _advance_retirement(worker: DisposableWorker, now: datetime) -> None:
    """Unknown state consumes bounded attempts, never capacity or custody."""
    from ._capacity_admit import release_range_capacity
    from ._cleanup_verification import is_range_generation_cleanup_verified_absent
    from ._principal_lifecycle import commit_prepared_range_lifecycle, prepare_system_range_cleanup
    from ._range_cleanup_retry import retry_range_cleanup_verification

    if worker.terminal_at is not None:
        return
    runtime = worker.range
    if runtime.status == "destroyed" and is_range_generation_cleanup_verified_absent(
        worker.request_id, worker.pk, runtime.pk
    ):
        worker.terminal_at = now
        worker.recovery_required = False
        worker.recovery_reason = ""
        worker.save(update_fields=["terminal_at", "recovery_required", "recovery_reason"])
        release_range_capacity(worker.pk, now=now)
    elif worker.recovery_required or (worker.next_recovery_at > now and worker.recovery_attempts):
        return
    elif worker.recovery_attempts >= worker.max_recovery_attempts:
        worker.recovery_required = True
        worker.recovery_reason = "cleanup-incomplete"
        worker.save(update_fields=["recovery_required", "recovery_reason"])
        return
    else:
        # The savepoint preserves a failed native dispatch without committing half
        # an operation; the outer transaction retains this recovery obligation.
        try:
            with transaction.atomic():
                if runtime.status == "destroyed":
                    retry_range_cleanup_verification(worker.request_id, now=now)
                else:
                    commit_prepared_range_lifecycle(prepare_system_range_cleanup(worker.request_id))
        except Exception:  # noqa: BLE001  # retained bounded recovery; provider/credential diagnostics stay private
            logger.warning("Worker cleanup pending worker_id=%s", worker.pk)
        worker.recovery_attempts += 1
        worker.next_recovery_at = now + timedelta(seconds=min(60 * 2 ** min(worker.recovery_attempts - 1, 6), 3600))
        worker.recovery_required = worker.recovery_attempts >= worker.max_recovery_attempts
        worker.recovery_reason = "cleanup-incomplete" if worker.recovery_required else "cleanup-pending"
        worker.save(update_fields=["recovery_attempts", "next_recovery_at", "recovery_required", "recovery_reason"])
