"""Custody primitives for one disposable worker: lock order and authorized lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import DisposableWorker, Range, WorkerPolicyRecord
from engine.services._range.authority import require_native_range_action

if TYPE_CHECKING:
    from uuid import UUID

    from shared.credentials import CredentialContext


def _lock_worker(worker_id: UUID) -> DisposableWorker:
    """Take the admission mutex before native range and retained custody locks."""

    WorkerPolicyRecord.objects.select_for_update().get(pk=1)
    native_id = DisposableWorker.objects.values_list("range_id", flat=True).get(pk=worker_id)
    runtime = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=native_id)
    worker = DisposableWorker.objects.select_for_update().get(pk=worker_id, range=runtime)
    worker.range = runtime
    return worker


def _authorized_worker(credential: CredentialContext, worker_id: UUID, action: str) -> DisposableWorker:
    """Resolve retained custody and require the exact current range action."""

    row = DisposableWorker.objects.select_related("range").get(pk=worker_id)
    require_native_range_action(credential, row.request_id, action)
    return row
