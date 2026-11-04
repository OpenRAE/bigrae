"""Fence native dispatch after an owning SDK outcome; never erase uncertain calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditActorType, AuditEntityType, AuditEvent, audit_log

from ._compiled_participants import _scope_digest
from ._native_participant_settlement import fence_native_power_work

if TYPE_CHECKING:
    from shared.native_participant import NativeRuntimeCoordinates


@contextmanager
def locked_native_participant_context(coordinates: NativeRuntimeCoordinates) -> Iterator[None]:
    """Serialize native cleanup with callbacks; this lock grants no permission."""
    from engine.models import RaesCompilerInputBinding, Range

    binding = RaesCompilerInputBinding.objects.only(
        "range_id",
        "resource_generation",
        "scope_digest",
    ).get(binding_ref=coordinates.binding_ref)
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=binding.range_id)
        if (
            row.resource_generation != coordinates.resource_generation
            or binding.resource_generation != coordinates.resource_generation
            or _scope_digest(row) != binding.scope_digest
        ):
            raise ValueError("Native cleanup context changed")
        yield


def fence_native_participant_dispatch(action_id: UUID, coordinates: NativeRuntimeCoordinates) -> None:
    """Private owner settlement; only never-invoked work restores its captured prior state."""
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range

    with locked_native_participant_context(coordinates):
        reservation = (
            ParticipantPowerReservation.objects.select_for_update()
            .select_related(
                "compiler_binding",
                "launch_intent",
            )
            .defer("compiler_binding__parameters_json", "compiler_binding__artifact_planning_json")
            .filter(action_id=action_id)
            .first()
        )
        if reservation is None:
            return
        if (
            reservation.run_id != coordinates.run_id
            or reservation.compiler_binding.binding_ref != coordinates.binding_ref
        ):
            raise ValueError("Native cleanup context changed")
        row = Range.objects.select_for_update().get(pk=reservation.compiler_binding.range_id)
        if reservation.fenced_at is not None:
            return
        invocation_issued = ParticipantPowerInvocation.objects.filter(
            reservation=reservation, permission_issued=True
        ).exists()
        reservation.fenced_at = timezone.now()
        reservation.save(update_fields=["fenced_at"])
        launch = reservation.launch_intent
        if row.provisioner_operation_id == launch.operation_id and row.status in {"pausing", "resuming", "failed"}:
            if not invocation_issued:
                if reservation.previous_status not in {"ready", "paused", "failed"}:
                    raise ValueError("Native prior status unavailable")
                row.status = reservation.previous_status
                row.provisioner_operation_id = None
                row.save(update_fields=["status", "provisioner_operation_id", "updated_at"])
            else:
                fence_native_power_work(row, reservation, timezone.now())
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                actor_type=AuditActorType.SYSTEM,
                request_id=str(launch.payload["request_id"]),
                new_state={
                    "native_dispatch_fenced": str(action_id),
                    "run_id": str(coordinates.run_id),
                    "native_permission_was_issued": invocation_issued,
                    "status": row.status,
                },
            ),
            strict=True,
        )
