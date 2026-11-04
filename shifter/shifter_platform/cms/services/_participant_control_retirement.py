"""Retire native routing only after the owning teardown proves the world absent."""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from cms.models import ParticipantControlBinding, RangeInstance
from engine.services import is_range_generation_cleanup_verified_absent
from shared.audit import AuditActorType, AuditEntityType, AuditEvent, audit_log


def retire_verified_native_participant_control(range_uuid: UUID) -> bool:
    """Bounded system cleanup; logical status and revoked user proof grant nothing."""
    with transaction.atomic():
        row = RangeInstance.all_objects.select_for_update().get(uuid=range_uuid)
        bindings = ParticipantControlBinding.objects.filter(range_uuid=row.uuid, invalidated_at__isnull=True)
        if not bindings.exists() or row.request is None or row.range_id is None:
            return False
        if not is_range_generation_cleanup_verified_absent(row.request.request_id, row.uuid, row.range_id):
            return False
        for binding in bindings.select_for_update():
            binding.invalidated_at = timezone.now()
            binding.save(update_fields=["invalidated_at"])
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.RANGE,
                    entity_id=row.pk,
                    entity_ref=str(row.uuid),
                    action="update",
                    actor_type=AuditActorType.SYSTEM,
                    request_id=str(row.request.request_id),
                    new_state={
                        "participant_control_binding_retired": str(binding.pk),
                        "run_id": str(binding.run_id),
                        "resource_generation": str(binding.resource_generation),
                        "cleanup_verified": True,
                    },
                ),
                strict=True,
            )
        return True
