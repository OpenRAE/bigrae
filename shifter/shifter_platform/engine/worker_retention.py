"""Native destructive admission fence, shared by callers and dispatch checks."""

from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from engine.models import Range


def fence_worker_retirement(runtime: Range, *, admit: bool = False) -> None:
    """The caller holds the native range row lock before this local fence."""
    from engine.models import DisposableWorker, WorkerRetirementHold

    worker = DisposableWorker.objects.filter(range_id=runtime.pk).first()
    if worker is None:
        return
    if WorkerRetirementHold.objects.filter(worker=worker, released_at__isnull=True).exists():
        raise ValueError("Worker retirement hold is active")
    if admit and worker.retirement_at is None:
        worker.retirement_at = timezone.now()
        worker.save(update_fields=["retirement_at"])
