"""Release exact, currently authorized participant work to the native launcher.

Only the installed runtime owner calls this after independently verifying its
committed SDK operation and current control cut. This grants launch delivery,
not permission for a later provider invocation. No HTTP input is accepted here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.utils import timezone

from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields

from ._native_participant_binding import locked_native_participant_operation

if TYPE_CHECKING:
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext
    from shared.native_participant import NativeRuntimeCoordinates

    from ._native_participant_binding import PreparedNativeParticipantOperation

_UNAVAILABLE = "Native participant operation unavailable"


def native_participant_power_was_released(
    coordinates: NativeRuntimeCoordinates,
    action_id: UUID,
    portable_operation_id: UUID,
) -> bool:
    """Read a past exact release; this cannot release work or grant a provider call."""
    from engine.models import ParticipantPowerReservation

    retained = (
        ParticipantPowerReservation.objects.filter(action_id=action_id)
        .values(
            "run_id",
            "portable_operation_uuid",
            "released_at",
            "compiler_binding__binding_ref",
            "compiler_binding__resource_generation",
        )
        .first()
    )
    if retained is None:
        return False
    if (
        retained["run_id"] != coordinates.run_id
        or retained["compiler_binding__binding_ref"] != coordinates.binding_ref
        or retained["compiler_binding__resource_generation"] != coordinates.resource_generation
    ):
        raise ValueError(_UNAVAILABLE)
    if retained["portable_operation_uuid"] is None and retained["released_at"] is None:
        return False
    if retained["portable_operation_uuid"] != portable_operation_id:
        raise ValueError(_UNAVAILABLE)
    return retained["released_at"] is not None


def release_native_participant_power(
    credential: CredentialContext,
    action_id: UUID,
    *,
    portable_operation_uuid: UUID,
    control_cut_digest: str,
    authority_target: TargetRef | None = None,
    admission: PreparedNativeParticipantOperation | None = None,
) -> UUID:
    """Strict-audit one HELD→PENDING transition under the unchanged native fence."""
    if not isinstance(portable_operation_uuid, UUID):
        raise ValueError(_UNAVAILABLE)
    with locked_native_participant_operation(
        credential,
        action_id,
        control_cut_digest,
        authority_target=authority_target,
        prepared=admission,
    ) as (row, reservation, intent):
        if reservation.portable_operation_uuid != portable_operation_uuid:
            raise ValueError(_UNAVAILABLE)
        if reservation.released_at is not None:
            return intent.operation_id
        if intent.status != "HELD":
            raise ValueError(_UNAVAILABLE)
        reservation.released_at = timezone.now()
        reservation.save(update_fields=["released_at"])
        intent.status = "PENDING"
        intent.next_attempt_at = reservation.released_at
        intent.save(update_fields=["status", "next_attempt_at"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                **principal_actor_fields(credential.principal),
                request_id=str(intent.payload["request_id"]),
                new_state={
                    "participant_admission": "released",
                    "action_id": str(action_id),
                    "portable_operation_ref": str(portable_operation_uuid),
                    "operation_id": str(intent.operation_id),
                },
            ),
            strict=True,
        )
        return intent.operation_id
