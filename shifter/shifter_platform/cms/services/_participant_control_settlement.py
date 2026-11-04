"""Translate trusted owning SDK outcomes into native dispatch exclusion only."""

from django.db import transaction
from django.utils import timezone

from cms.models import ParticipantControlBinding, ParticipantControlCommand
from engine.services import fence_native_participant_dispatch, locked_native_participant_context
from shared.audit import AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.native_participant import NativeControlCommandRecord, NativeRuntimeCoordinates


def settle_native_control_dispatch(
    command: NativeControlCommandRecord,
    coordinates: NativeRuntimeCoordinates,
    *,
    cancelled_review: bool = False,
) -> None:
    """Only the fixed owner calls this after a failed receipt or accepted review cancellation.

    No caller can supply a verdict. Native command exclusion commits before
    checking for a reservation, under the same range lock its callback must
    acquire and revalidate. An absent reservation cannot authorize a late one.
    """
    with transaction.atomic(), locked_native_participant_context(coordinates):
        binding = ParticipantControlBinding.objects.select_for_update().get(pk=command.binding_id)
        if (binding.compiler_binding_ref, binding.resource_generation, binding.run_id) != (
            coordinates.binding_ref,
            coordinates.resource_generation,
            coordinates.run_id,
        ):
            raise ValueError("Native control cleanup context changed")
        affected = ParticipantControlCommand.objects.select_for_update().filter(binding=binding)
        if cancelled_review:
            affected = affected.filter(proposal_uuid=command.proposal_id, kind="action")
        else:
            affected = affected.filter(pk=command.id)
        for row in affected:
            if row.dispatch_fenced_at is None:
                row.dispatch_fenced_at = timezone.now()
                row.save(update_fields=["dispatch_fenced_at"])
                audit_log(
                    AuditEvent(
                        entity_type=AuditEntityType.RANGE,
                        entity_id=0,
                        entity_ref=str(binding.range_uuid),
                        action="update",
                        actor_type=AuditActorType.SYSTEM,
                        new_state={
                            "native_command_dispatch_fenced": str(row.pk),
                            "run_id": str(binding.run_id),
                            "cancelled_review": cancelled_review,
                        },
                    ),
                    strict=True,
                )
            if row.kind == "action":
                fence_native_participant_dispatch(row.action_uuid, coordinates)
