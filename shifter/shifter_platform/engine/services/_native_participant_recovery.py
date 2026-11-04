"""Bounded read-only reconciliation of already consumed native power calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.native_participant import NativePowerInvocationGrant
from shared.native_power_protocol import NATIVE_POWER_JOB_DEADLINE_SECONDS

from ._compiled_participants import _scope_digest
from ._native_participant_invocation_input import retained_native_power_input
from ._native_participant_settlement import fence_native_power_work

if TYPE_CHECKING:
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range
    from shared.raes.power_input import NativePowerInput, NativePowerMember

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NativePowerRecoveryBatch:
    """Native scan progress only; this is no operation or portable verdict."""

    cursor: UUID | None
    examined: int
    settled: int


@dataclass(frozen=True, slots=True)
class _RecoveryContext:
    """Original native metadata retained across read-only provider observation."""

    retained: ParticipantPowerInvocation
    power: NativePowerInput
    member: NativePowerMember
    row: Range


def reconcile_native_power_invocation(invocation_id: UUID) -> bool:
    """Fence existing work before observing and closing only its exact ceased call."""
    from shared.cloud import get_native_power_observer

    context = _recovery_context(invocation_id)
    if context is None or not _fence_recovery(context):
        return False
    retained, power, member = context.retained, context.power, context.member
    reservation = retained.reservation
    grant = NativePowerInvocationGrant(
        invocation_id=retained.pk,
        operation_id=reservation.launch_intent.operation_id,
        resource_generation=power.resource_generation,
        verb=reservation.launch_intent.payload["operation"],
        member_ref=retained.member_ref,
        target=member.target,
        incarnation=member.incarnation,
        attempt_id=retained.attempt_id,
    )
    provider_reference = get_native_power_observer().completed_call(grant)
    return provider_reference is not None and _settle_recovery(context, grant, provider_reference)


def _recovery_context(invocation_id: UUID) -> _RecoveryContext | None:
    """Select only open issued permissions in their unchanged native context."""
    from engine.models import ParticipantPowerInvocation, Range

    retained = (
        ParticipantPowerInvocation.objects.select_related(
            "reservation__launch_intent",
            "reservation__compiler_binding",
        )
        .defer(
            "reservation__compiler_binding__parameters_json", "reservation__compiler_binding__artifact_planning_json"
        )
        .get(pk=invocation_id)
    )
    if retained.closed_at is not None or not retained.permission_issued:
        return None
    reservation = retained.reservation
    power = retained_native_power_input(reservation)
    members = [member for member in power.members if member.member_ref == retained.member_ref]
    row = Range.objects.get(pk=reservation.compiler_binding.range_id)
    if (
        len(members) != 1
        or not retained.container_id
        or row.resource_generation != power.resource_generation
        or _scope_digest(row) != reservation.compiler_binding.scope_digest
        or not _same_native_work(row, reservation)
        or not _recovery_needed(row, retained)
    ):
        return None
    return _RecoveryContext(retained, power, members[0], row)


def _recovery_needed(row: Range, retained: ParticipantPowerInvocation) -> bool:
    """Preserve a live worker's bounded post-call observation and readiness window."""
    # A healthy worker needs time for its post-call readback and readiness
    # evidence. Job absence is only a recovery trigger; it is never proof that
    # an already issued provider call has ceased.
    inactive = (
        row.status == "failed"
        or retained.reservation.fenced_at is not None
        or (timezone.now() - retained.created_at >= timedelta(seconds=NATIVE_POWER_JOB_DEADLINE_SECONDS))
    )
    if not inactive:
        from shared.cloud import get_task_runner
        from shared.cloud.kubernetes import KubernetesTaskRunner

        runner = get_task_runner()
        if not isinstance(runner, KubernetesTaskRunner):
            return False
        launch = retained.reservation.launch_intent
        inactive = runner.is_task_invocation_inactive(
            cluster=launch.executing_workload["namespace"],
            task_ref=launch.task_ref,
            expected_identity=launch.executing_workload,
            job_uid=retained.job_uid,
        )
    return inactive


def _fence_recovery(context: _RecoveryContext) -> bool:
    """Commit exclusion before any independent cloud observation."""
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range

    retained, power, row = context.retained, context.power, context.row
    reservation, invocation_id = retained.reservation, retained.pk
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=row.pk)
        current = ParticipantPowerReservation.objects.select_for_update().get(pk=reservation.pk)
        invocation = ParticipantPowerInvocation.objects.select_for_update().get(pk=invocation_id)
        if invocation.closed_at is not None:
            return False
        if (
            row.resource_generation != power.resource_generation
            or _scope_digest(row) != reservation.compiler_binding.scope_digest
            or not _same_native_work(row, reservation)
        ):
            return False
        if current.fenced_at is None:
            fence_native_power_work(row, current, timezone.now())
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.RANGE,
                    entity_id=row.pk,
                    entity_ref=str(row.cms_range_uuid),
                    action="update",
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=None,
                    context="Bounded native call recovery",
                    request_id=str(reservation.launch_intent.payload["request_id"]),
                    new_state={
                        "native_invocation": str(invocation_id),
                        "native_work_fenced": True,
                        "call_cessation_unresolved": True,
                    },
                ),
                strict=True,
            )
    return True


def _settle_recovery(
    context: _RecoveryContext,
    grant: NativePowerInvocationGrant,
    provider_reference: str,
) -> bool:
    """Close only the unchanged original permission, with strict cessation audit."""
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range

    retained, power = context.retained, context.power
    reservation, invocation_id = retained.reservation, retained.pk
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=reservation.compiler_binding.range_id)
        current = ParticipantPowerReservation.objects.select_for_update().get(pk=reservation.pk)
        invocation = ParticipantPowerInvocation.objects.select_for_update().get(pk=invocation_id)
        if invocation.closed_at is not None:
            return False
        if (
            invocation.reservation_id != current.pk
            or invocation.attempt_id != retained.attempt_id
            or invocation.container_id != retained.container_id
            or row.resource_generation != power.resource_generation
            or _scope_digest(row) != reservation.compiler_binding.scope_digest
            or not _same_native_work(row, reservation)
        ):
            raise ValueError("Native recovery binding changed")
        now = timezone.now()
        invocation.closed_at = now
        invocation.save(update_fields=["closed_at"])
        fence_native_power_work(row, current, now)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                context="Bounded native call recovery",
                request_id=str(reservation.launch_intent.payload["request_id"]),
                new_state={
                    "native_invocation": str(invocation_id),
                    "operation_id": str(grant.operation_id),
                    "completed_provider_operation": provider_reference,
                    "native_work_fenced": True,
                    "resource_generation": str(power.resource_generation),
                },
            ),
            strict=True,
        )
    return True


def _same_native_work(row: Range, reservation: ParticipantPowerReservation) -> bool:
    """An independent fenced teardown may replace work, never custody or generation."""
    return row.provisioner_operation_id == reservation.launch_intent.operation_id or (
        reservation.fenced_at is not None
        and row.provisioner_operation == "raes-range:destroy"
        and row.status in {"destroying", "destroyed", "failed"}
    )


def reconcile_native_power_invocations(*, cursor: UUID | None = None, limit: int = 8) -> NativePowerRecoveryBatch:
    """Rotate over bounded records so an unknown old call cannot starve another."""
    from engine.models import ParticipantPowerInvocation

    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("Native recovery scan limit unavailable")
    rows = ParticipantPowerInvocation.objects.filter(closed_at__isnull=True, permission_issued=True).order_by("pk")
    if cursor is not None:
        rows = rows.filter(pk__gt=cursor)
    identities = list(rows.values_list("pk", flat=True)[:limit])
    settled = 0
    for identity in identities:
        try:
            settled += reconcile_native_power_invocation(identity)
        except Exception as exc:  # noqa: BLE001  # retain exclusion; only opaque references and fault classes are observable
            logger.warning("Native recovery unavailable invocation=%s exc_type=%s", identity, type(exc).__name__)
    return NativePowerRecoveryBatch(identities[-1] if identities else None, len(identities), settled)
