"""Retry native range cleanup after its former cleanup worker stopped."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus, Range

from ._principal_lifecycle import _commit_destroy, prepare_system_range_cleanup


def retry_due_failed_cleanup_tasks(limit: int = 3) -> int:
    """The privileged launcher alone observes retained cleanup, once per minute."""

    now = timezone.now()
    intents = ProvisionerLaunchIntent.objects.filter(
        operation_id__in=Range.objects.filter(status="destroying").values("provisioner_operation_id"),
        authority_kind="cleanup",
        status=ProvisionerLaunchStatus.SUCCEEDED,
        payload__operation="destroy",
        next_attempt_at__lte=now,
    ).order_by("next_attempt_at")[:limit]
    processed = 0
    for intent in intents:
        claimed = ProvisionerLaunchIntent.objects.filter(
            pk=intent.pk, next_attempt_at=intent.next_attempt_at, status=ProvisionerLaunchStatus.SUCCEEDED
        ).update(next_attempt_at=now + timedelta(minutes=1))
        if not claimed:
            continue
        row = (
            Range.objects.select_related("request")
            .filter(status="destroying", provisioner_operation_id=intent.operation_id)
            .first()
        )
        if row is None or row.request is None:
            continue
        try:
            _commit_destroy(prepare_system_range_cleanup(row.request.request_id), _failed_task_retry=True)
        except (ValueError, PermissionError):
            # A concurrent lifecycle change retains custody and the current task.
            continue
        processed += 1
    return processed
