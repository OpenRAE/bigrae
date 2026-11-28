"""Read-only admission queries for authoritative operation-result apply."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Q

from engine.models import OperationResultDisposition
from engine.models import OperationResultInbox as Inbox

if TYPE_CHECKING:
    from engine.models import OperationResultInbox


def discriminator_mismatch(row: OperationResultInbox, envelope: dict[str, Any]) -> str:
    """Return a reason when a flattened inbox column disagrees with the envelope."""
    for field in ("operation_id", "request_id", "resource", "operation", "contract_version"):
        if str(getattr(row, field)) != str(envelope[field]):
            return f"inbox {field} does not match the envelope"
    return ""


def has_conflicting_sibling(row: OperationResultInbox) -> bool:
    """Return whether this step has another row with a different payload."""

    digests = (
        Inbox.objects.filter(operation_id=row.operation_id, result_step=row.result_step)
        .values_list("payload_digest", flat=True)
        .distinct()
    )
    return len(set(digests)) > 1


def applied_steps(row: OperationResultInbox) -> list[str]:
    """Return the steps already applied for this operation generation."""

    return list(
        Inbox.objects.filter(
            operation_id=row.operation_id,
            disposition=OperationResultDisposition.APPLIED,
        )
        .exclude(result_step="")
        .values_list("result_step", flat=True)
    )


def has_earlier_pending_sibling(row: OperationResultInbox) -> bool:
    """Return whether an earlier result of this generation is pending.

    Order is ``(created_at, pk)``, the applier's claim order. The insertion-ordered
    primary key breaks a ``created_at`` tie between sibling results.
    """
    earlier = Q(created_at__lt=row.created_at) | Q(created_at=row.created_at, pk__lt=row.pk)
    return Inbox.objects.filter(
        earlier,
        operation_id=row.operation_id,
        disposition=OperationResultDisposition.PENDING,
    ).exists()
