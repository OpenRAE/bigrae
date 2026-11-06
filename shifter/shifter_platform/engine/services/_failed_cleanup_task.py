"""Retire only a failed, identity-checked cleanup task before a native retry."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.utils import timezone

from shared.cloud import get_task_runner
from shared.cloud.exceptions import CloudTaskError

if TYPE_CHECKING:
    from engine.models import ProvisionerLaunchIntent

_IDENTITY_FIELDS = ("task_identity", "image", "container_name", "service_account_name")


def retire_failed_cleanup_task(intent: "ProvisionerLaunchIntent") -> bool:
    """Unknown or changed provider evidence cannot authorize duplicate effects."""
    from engine.models import ProvisionerLaunchStatus

    selected = _recorded_identity(intent) if intent.status == ProvisionerLaunchStatus.SUCCEEDED else None
    retired = False
    if selected is not None:
        namespace, identity = selected
        runner = get_task_runner()
        try:
            observed = runner.get_task_status(cluster=namespace, task_id=intent.task_ref)
            if observed is not None and observed.get("status") == "FAILED":
                runner.delete_completed_task(namespace, intent.task_ref, identity)
                retired = True
        except CloudTaskError:
            # Provider errors can include private diagnostics. Retain custody.
            pass
    return retired


def _recorded_identity(intent: "ProvisionerLaunchIntent") -> tuple[str, dict[str, Any]] | None:
    """Use the admitted workload, never current settings or caller-supplied task fields."""
    workload = intent.executing_workload
    if not isinstance(workload, dict) or not _valid_workload_values(workload):
        return None
    namespace, name = workload["namespace"], workload["job_name"]
    if workload["provider"] != settings.CLOUD_PROVIDER or intent.task_ref != namespace + "/" + name:
        return None
    identity = {key: workload[key] for key in (*_IDENTITY_FIELDS, "command")}
    identity["service_account_name"] = workload["service_account_name"] or "default"
    return namespace, identity


def _valid_workload_values(workload: dict[str, Any]) -> bool:
    """Require the full recorded identity before asking the provider to verify it."""
    strings = ("task_identity", "image", "container_name", "provider", "namespace", "job_name")
    command = workload.get("command")
    return (
        all(isinstance(workload.get(key), str) and workload[key] for key in strings)
        and isinstance(workload.get("service_account_name"), str)
        and isinstance(command, list)
        and bool(command)
        and all(isinstance(part, str) for part in command)
    )


def retry_due_failed_cleanup_tasks(limit: int = 3) -> int:
    """The privileged launcher alone observes retained cleanup, once per minute."""
    from engine.models import ProvisionerLaunchIntent, ProvisionerLaunchStatus, Range

    from ._principal_lifecycle import _commit_destroy, prepare_system_range_cleanup

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
