"""Durably deliver CMS range status changes to local CTF receivers."""

from __future__ import annotations

import logging
from datetime import timedelta
from functools import partial

from django.db import transaction
from django.db.models import Count, Exists, Min, OuterRef, Q
from django.utils import timezone

from cms.models import RangeStatusDelivery
from cms.signals import range_status_changed

logger = logging.getLogger(__name__)


def notify_ctf_range_status(
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    cleanup_verified: bool = False,
) -> None:
    """Persist delivery with the caller's CMS status write; attempt it after commit.

    CTF receivers run only after the outermost CMS transaction commits, in their
    own transaction, so a CTF failure or lock wait never delays or rolls back the
    CMS write. A rollback discards the delivery and the attempt together. A failed
    or lost attempt leaves the delivery for the existing range reconciler.
    Captured cleanup proof must survive replay: a logical DESTROYED status alone
    never authorizes capacity/linkage release.
    """
    RangeStatusDelivery.objects.create(
        range_instance_id=range_instance_id,
        new_status=new_status,
        previous_status=previous_status,
        cleanup_verified=cleanup_verified,
    )
    transaction.on_commit(partial(_deliver_after_commit, range_instance_id))


def _deliver_after_commit(range_instance_id: int) -> None:
    """Accelerate delivery after commit; the reconciler retries anything left."""
    try:
        drain_ctf_status_deliveries(range_instance_id=range_instance_id)
    except Exception as exc:  # noqa: BLE001  # the committed delivery row is the durable retry
        logger.error(
            "CTF range status delivery deferred to reconciler range_instance_id=%s exc_type=%s",
            range_instance_id,
            type(exc).__name__,
            exc_info=False,
        )


def drain_ctf_status_deliveries(*, limit: int = 100, range_instance_id: int | None = None) -> int:
    """Retry bounded pending deliveries, preserving status order for each range."""
    earlier = RangeStatusDelivery.objects.filter(range_instance_id=OuterRef("range_instance_id"), pk__lt=OuterRef("pk"))
    pending = RangeStatusDelivery.objects.filter(~Exists(earlier), next_attempt_at__lte=timezone.now()).order_by("pk")
    if range_instance_id is not None:
        pending = pending.filter(range_instance_id=range_instance_id)
    identities = dict.fromkeys(pending.values_list("range_instance_id", flat=True)[:limit])
    delivered = 0
    for identity in identities:
        while delivered < limit and _deliver_next(identity):
            delivered += 1
    return delivered


def ctf_status_delivery_backlog() -> dict[str, int]:
    """Return pending and retrying delivery counts and the oldest pending age in seconds."""
    summary = RangeStatusDelivery.objects.aggregate(
        pending=Count("pk"),
        retrying=Count("pk", filter=Q(attempts__gt=0)),
        oldest=Min("created_at"),
    )
    oldest = summary["oldest"]
    age = int((timezone.now() - oldest).total_seconds()) if oldest is not None else 0
    return {"pending": summary["pending"], "retrying": summary["retrying"], "oldest_age_seconds": age}


def _deliver_next(range_instance_id: int) -> bool:
    """Commit receiver writes and delivery removal together, or retain a retry.

    Only the head delivery row is locked. Concurrent drainers serialize on it, and
    no CMS projection lock is held, so CMS status writes never wait on CTF work.
    """
    with transaction.atomic():
        delivery = (
            RangeStatusDelivery.objects.select_for_update()
            .filter(range_instance_id=range_instance_id)
            .order_by("pk")
            .first()
        )
        if delivery is None or delivery.next_attempt_at > timezone.now():
            return False
        error_type = _send(delivery)
        if error_type is not None:
            # Recorded outside the receiver's except block, so a metadata write
            # failure cannot chain the receiver exception into a traceback.
            _schedule_retry(delivery, error_type)
            return False
        delivery.delete()
    return True


def _send(delivery: RangeStatusDelivery) -> str | None:
    """Run the receivers in a savepoint; return the failure class, or None on success."""
    try:
        with transaction.atomic():
            range_status_changed.send(
                sender=None,
                range_instance_id=delivery.range_instance_id,
                new_status=delivery.new_status,
                previous_status=delivery.previous_status,
                cleanup_verified=delivery.cleanup_verified,
            )
    except Exception as exc:  # noqa: BLE001
        # Receiver errors can contain private data; persist/log the class only.
        return type(exc).__name__[:128]
    return None


def _schedule_retry(delivery: RangeStatusDelivery, error_type: str) -> None:
    """Record the failure class and back off exponentially, capped at five minutes."""
    delivery.attempts += 1
    delivery.last_error_type = error_type
    delay = min(300, 2 ** min(delivery.attempts, 9))
    delivery.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    delivery.save(update_fields=["attempts", "last_error_type", "next_attempt_at"])
    logger.error(
        "CTF range status delivery retained for retry delivery_id=%s range_instance_id=%s exc_type=%s",
        delivery.pk,
        delivery.range_instance_id,
        error_type,
        exc_info=False,
    )
