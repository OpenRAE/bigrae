"""Dispatch-failure lifecycle for provisioner launch intents.

Split out of :mod:`engine.services._launch.intents` (Sonar S104) alongside the earlier
``operation_inputs`` split. Owns the "a provider dispatch failed, close the
episode" concern: resolving and locking the failed domain row, confirming the
failure still owns the current generation, and persisting the sanitized FAILED
projection plus its status event. The two public entry points are re-exported
from :mod:`engine.services._launch.intents` so existing importers are unaffected.

Imports of ``authorize_provisioner_payload`` / ``command_from_payload`` back from
``launch_intents`` are deferred (function-local) so the top-level import graph
stays one-directional (``launch_intents`` -> this module).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.utils import timezone

from engine.launch_commands import command_from_payload
from engine.launch_target import lock_provisioner_target
from engine.models import App, GcpRangeProject, Instance, Range, RangeEventOutbox
from engine.services._gcp_project.operations import validate_project_operation
from engine.services._launch.generation import validate_provisioner_generation
from engine.services._principal.range_events import range_status_authority_fields
from engine.services._range.receipt import _revoke_receipt_verifier_for_range
from engine.services._worker.trials import fail_worker_trial_dispatch
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_STATUS_UPDATED

PROVISIONER_DISPATCH_FAILED = "Provisioner dispatch failed"


def clear_provisioner_operation_after_failure(row: Range | Instance) -> list[str]:
    """Close a failed lifecycle episode so the same operation can be retried."""
    if row.provisioner_operation_id is None and not row.provisioner_operation:
        return []
    row.provisioner_operation = ""
    row.provisioner_operation_id = None
    return ["provisioner_operation", "provisioner_operation_id"]


def _generation_still_authorizes_failure(
    payload: dict[str, object],
    target: Range | Instance,
    expected_operation_id: UUID | str,
) -> bool:
    """Return whether a provider failure still owns the current lifecycle."""

    try:
        validate_provisioner_generation(
            payload,
            target=target,
            expected_operation_id=expected_operation_id,
        )
    except ValueError:
        return False
    return True


def _publish_range_dispatch_failure(payload: dict[str, object], target: Range) -> None:
    """Publish the standard failed status event for a Range dispatch."""

    event_id = uuid4()
    related_request = target.request
    request_id = str(related_request.request_id) if related_request is not None else str(payload.get("request_id", ""))
    event = {
        "event_type": EVENT_TYPE_STATUS_UPDATED,
        "event_id": str(event_id),
        "timestamp": timezone.now().isoformat(),
        "request_id": request_id,
        "range_id": target.id,
        "user_id": target.user_id,
        "new_status": ResourceStatus.FAILED.value,
        "error_message": PROVISIONER_DISPATCH_FAILED,
        **range_status_authority_fields(target),
    }
    RangeEventOutbox.objects.create(
        event_id=event_id,
        event_type=EVENT_TYPE_STATUS_UPDATED,
        payload=event,
        next_attempt_at=timezone.now(),
    )


def _apply_dispatch_failure(payload: dict[str, object], target: Range | Instance) -> None:
    """Persist the sanitized failure state and its dependent projections."""

    target.status = ResourceStatus.FAILED.value
    update_fields = ["status", "updated_at"]
    update_fields.extend(clear_provisioner_operation_after_failure(target))
    if isinstance(target, Range):
        target.error_message = PROVISIONER_DISPATCH_FAILED
        update_fields.append("error_message")
    target.save(update_fields=update_fields)
    if isinstance(target, Range):
        _revoke_receipt_verifier_for_range(target)
        _publish_range_dispatch_failure(payload, target)
    else:
        App.objects.filter(instance=target).update(
            status=ResourceStatus.FAILED.value,
            updated_at=timezone.now(),
        )


def fail_current_provisioner_operation(
    payload: dict[str, object],
    expected_operation_id: UUID | str,
) -> bool:
    """Fail only the domain projection still owned by this operation generation."""

    try:
        command_from_payload(payload)
    except (KeyError, TypeError, ValueError):
        return False
    target = lock_provisioner_target(payload)
    if payload.get("resource") == "worker-trial":
        return fail_worker_trial_dispatch(payload, expected_operation_id)
    if isinstance(target, GcpRangeProject):
        failed = _fail_project_registration(payload, expected_operation_id, target)
    elif not isinstance(target, (Range, Instance)) or not _generation_still_authorizes_failure(
        payload, target, expected_operation_id
    ):
        failed = False
    else:
        _apply_dispatch_failure(payload, target)
        failed = True
    return failed


def _fail_project_registration(
    payload: dict[str, object], expected_operation_id: UUID | str, target: GcpRangeProject
) -> bool:
    """Only the still-current registration generation may record a dispatch failure."""

    try:
        validate_project_operation(payload, expected_operation_id)
    except ValueError:
        return False
    target.status, target.failure_code = "failed", "dispatch-failed"
    target.save(update_fields=["status", "failure_code", "updated_at"])
    return True
