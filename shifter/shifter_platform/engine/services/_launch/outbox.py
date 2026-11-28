"""Claim, launch, and settle one durable provisioner launch intent.

The dedicated launcher command drains intents through these steps. Local
provisioner mode launches one committed intent through the same steps.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from engine.ecs import dispatch_provisioner_command
from engine.launch_commands import command_from_payload
from engine.launch_target import lock_provisioner_target
from engine.models import InterruptState, ProvisionerLaunchIntent, ProvisionerLaunchStatus
from engine.services._launch.dispatch_failure import fail_current_provisioner_operation
from engine.services._launch.generation import assert_provisioner_input_matches, validate_provisioner_generation
from engine.services._launch.payload_authority import authorize_provisioner_payload
from shared.credentials import resolve_local_credential
from shared.operation_authority import credential_reference_from_record

# Keep the launcher command's logger name so log routing and dashboards do not change.
logger = logging.getLogger("engine.management.commands.drain_provisioner_launch_outbox")


def drain_local_intent(intent_id: UUID) -> None:
    """Wake the canonical launcher for exactly one committed local intent."""
    row = claim_next_intent(intent_id=intent_id)
    if row is not None:
        launch_intent(row)


def claim_next_intent(*, intent_id: UUID | None = None) -> ProvisionerLaunchIntent | None:
    """Lease the next due, uninterrupted launch intent, or the named one."""
    with transaction.atomic():
        row = (
            ProvisionerLaunchIntent.objects.select_for_update(skip_locked=True)
            .filter(**({"intent_id": intent_id} if intent_id is not None else {}))
            .filter(
                Q(status=ProvisionerLaunchStatus.PENDING) | Q(status=ProvisionerLaunchStatus.RUNNING),
                # Never launch or relaunch an intent whose provision was cancelled
                # (#277); the interrupt drainer suppresses and converges it.
                interrupt_state=InterruptState.NONE,
                next_attempt_at__lte=timezone.now(),
            )
            .order_by("next_attempt_at")
            .first()
        )
        if row is None:
            return None
        row.status = ProvisionerLaunchStatus.RUNNING
        row.next_attempt_at = timezone.now() + timedelta(minutes=5)
        row.save(update_fields=["status", "next_attempt_at"])
        return row


def launch_intent(row: ProvisionerLaunchIntent) -> None:
    """Authorize, fence, and dispatch one claimed intent, then record the outcome."""
    try:
        # Carry the canonical operation_id onto the launched argv so the
        # provisioner tags its input read and result appends with exactly the
        # operation it is executing, never "latest by request" (ADR-043).
        command = command_from_payload({**row.payload, "operation_id": str(row.operation_id)})
        authorize_provisioner_payload(row.payload, expected_operation_id=row.operation_id)
        # Lock the domain projection while validating the operation generation.
        # This linearizes a stale launch against a concurrent lifecycle transition:
        # either this generation is authorized first, or the newer generation wins
        # and this intent is rejected before provider dispatch.
        with transaction.atomic():
            lock_provisioner_target(row.payload)
            current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=row.pk)
            if not _lease_matches(current, row):
                logger.info("ignoring stale provisioner launch lease intent_id=%s", row.intent_id)
                return
            if current.interrupt_state != InterruptState.NONE:
                # A cancellation landed after this intent was claimed: do not
                # dispatch (#277). Release the launch lease so the intent is not
                # stuck RUNNING; the interrupt drainer converges it to destroy.
                current.status = ProvisionerLaunchStatus.PENDING
                current.next_attempt_at = timezone.now()
                current.save(update_fields=["status", "next_attempt_at"])
                logger.info("provisioner launch suppressed by interrupt intent_id=%s", row.intent_id)
                return
            validate_provisioner_generation(row.payload, expected_operation_id=row.operation_id)
            assert_provisioner_input_matches(row.payload, row.operation_id)
            if current.authority_kind in {"principal", "warm_pool"}:
                recorded = credential_reference_from_record(current)
                if resolve_local_credential(recorded) != recorded:
                    raise ValueError("Provisioner launch credential changed")
            task_ref = dispatch_provisioner_command(
                command,
                task_identity=str(row.intent_id),
                **({"expected_workload": current.executing_workload} if current.authority_kind else {}),
            )
        if not task_ref:
            raise RuntimeError("provisioner task runner is not configured")
    except Exception as exc:  # noqa: BLE001  # dispatch errors can echo the Job spec; record the type only
        _record_failure(row, exc)
        return
    _record_success(row, task_ref)


def _lease_matches(current: ProvisionerLaunchIntent, claimed: ProvisionerLaunchIntent) -> bool:
    """Fence a worker whose RUNNING lease was reclaimed while it was dispatching."""
    return current.status == ProvisionerLaunchStatus.RUNNING and current.next_attempt_at == claimed.next_attempt_at


def _record_failure(row: ProvisionerLaunchIntent, exc: Exception) -> None:
    with transaction.atomic():
        lock_provisioner_target(row.payload)
        current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=row.pk)
        if not _lease_matches(current, row):
            logger.info("ignoring stale provisioner launch failure intent_id=%s", row.intent_id)
            return
        if current.interrupt_state != InterruptState.NONE:
            return
        current.attempts += 1
        current.last_error = type(exc).__name__[:128]
        if current.attempts >= current.max_attempts:
            current.status = ProvisionerLaunchStatus.DLQ
            fail_current_provisioner_operation(current.payload, current.operation_id)
        else:
            current.status = ProvisionerLaunchStatus.PENDING
            current.next_attempt_at = timezone.now() + timedelta(seconds=min(60 * 2 ** (current.attempts - 1), 3600))
        current.save(update_fields=["status", "attempts", "last_error", "next_attempt_at"])
    if current.status == ProvisionerLaunchStatus.DLQ:
        logger.error(
            "provisioner launch moved to DLQ intent_id=%s error_type=%s attempts=%s",
            current.intent_id,
            current.last_error,
            current.attempts,
        )
        return
    logger.warning(
        "provisioner launch failed intent_id=%s error_type=%s",
        current.intent_id,
        current.last_error,
    )


def _record_success(row: ProvisionerLaunchIntent, task_ref: str) -> None:
    with transaction.atomic():
        current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=row.pk)
        if not _lease_matches(current, row):
            logger.info("ignoring stale provisioner launch success intent_id=%s", row.intent_id)
            return
        current.status = ProvisionerLaunchStatus.SUCCEEDED
        current.task_ref = task_ref
        current.last_error = ""
        current.launched_at = timezone.now()
        if current.authority_kind == "cleanup":
            current.next_attempt_at = current.launched_at + timedelta(minutes=1)
        current.save(update_fields=["status", "task_ref", "last_error", "launched_at", "next_attempt_at"])
