"""Native grant settlement without granting or replaying a cloud operation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from pydantic import SecretStr

from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.native_participant import native_power_invocation_id

from ._compiled_participants import _scope_digest
from ._native_participant_invocation import _authenticate_worker
from ._native_participant_invocation_input import retained_native_power_input

if TYPE_CHECKING:
    from datetime import datetime

    from engine.models import ParticipantPowerReservation, Range

_UNAVAILABLE = "Native participant invocation withdrawal unavailable"


def fence_native_power_work(row: Range, reservation: ParticipantPowerReservation, now: datetime) -> None:
    """Stop later grants before closing an uncertain permission or pre-call attempt."""
    if reservation.fenced_at is None:
        reservation.fenced_at = now
        reservation.save(update_fields=["fenced_at"])
    launch = reservation.launch_intent
    if (
        row.resource_generation == reservation.compiler_binding.resource_generation
        and row.provisioner_operation_id == launch.operation_id
        and row.status in {"pausing", "resuming", "failed"}
    ):
        from ._operation_apply_domain import _apply_failure

        _apply_failure(
            row,
            {"reason_code": "cloud_operation_failed"},
            str(launch.payload["request_id"]),
            is_range=True,
        )


def withdraw_native_power_invocation(
    *,
    operation_id: UUID,
    member_ref: str,
    attempt_id: UUID,
    token: SecretStr,
) -> None:
    """The fixed worker has not called the provider; fence even a late acquisition.

    The authenticated attempt occupies the same unique member slot with no
    issued permission when acquisition has not committed. Another attempt cannot
    withdraw an existing uncertain call. No initiating proof is borrowed after
    revocation, and no cloud request, portable verdict or readiness is inferred.
    """
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range
    from shared.operation_authority import credential_reference_from_record

    if not isinstance(attempt_id, UUID) or not attempt_id.int:
        raise ValueError(_UNAVAILABLE)
    retained = (
        ParticipantPowerReservation.objects.select_related(
            "launch_intent",
            "compiler_binding",
        )
        .defer("compiler_binding__parameters_json", "compiler_binding__artifact_planning_json")
        .get(launch_intent__operation_id=operation_id)
    )
    worker = _authenticate_worker(retained, token, for_completion=True)
    power = retained_native_power_input(retained)
    if member_ref not in {member.member_ref for member in power.members}:
        raise ValueError(_UNAVAILABLE)
    invocation_id = native_power_invocation_id(operation_id, member_ref)
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=retained.compiler_binding.range_id)
        reservation = ParticipantPowerReservation.objects.select_for_update().get(pk=retained.pk)
        if (
            row.provisioner_operation_id != operation_id
            or row.resource_generation != retained.compiler_binding.resource_generation
            or _scope_digest(row) != retained.compiler_binding.scope_digest
        ):
            # A current native fence already prevents this original operation
            # from acquiring permission. Do not write into changed custody.
            return
        invocation = ParticipantPowerInvocation.objects.select_for_update().filter(pk=invocation_id).first()
        now = timezone.now()
        if invocation is not None:
            if (
                invocation.reservation_id,
                invocation.attempt_id,
                invocation.pod_uid,
                invocation.job_uid,
                invocation.container_id,
            ) != (
                reservation.pk,
                attempt_id,
                worker.pod_uid,
                worker.job_uid,
                worker.container_id,
            ):
                raise ValueError(_UNAVAILABLE)
            if invocation.closed_at is not None:
                if reservation.fenced_at is None:
                    raise ValueError(_UNAVAILABLE)
                return
            invocation.closed_at = now
            invocation.save(update_fields=["closed_at"])
        else:
            invocation = ParticipantPowerInvocation.objects.create(
                invocation_id=invocation_id,
                reservation=reservation,
                member_ref=member_ref,
                attempt_id=attempt_id,
                pod_uid=worker.pod_uid,
                pod_name=worker.pod_name,
                job_uid=worker.job_uid,
                container_id=worker.container_id,
                permission_issued=False,
                closed_at=now,
            )
        fence_native_power_work(row, reservation, now)
        credential = credential_reference_from_record(retained.launch_intent)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                **principal_actor_fields(credential.principal),
                request_id=str(retained.launch_intent.payload["request_id"]),
                new_state={
                    "native_invocation": str(invocation_id),
                    "operation_id": str(operation_id),
                    "pre_call_withdrawal": True,
                    "permission_issued": invocation.permission_issued,
                },
            ),
            strict=True,
        )
