"""CTF signal receivers for CMS events.

Connects to CMS signals to keep CTF data in sync with range status changes.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from cms.services import range_status_changed
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from ctf.models import CTFParticipant

logger = logging.getLogger(__name__)

from ctf.models import (  # noqa: E402  # Django signal senders are imported after setup
    CTFChallenge,
    CTFEvent,
    CTFEventPage,
    CTFNotification,
)


def _declare_range_ready(participant: CTFParticipant, *, publish: bool) -> None:
    """Declare range-ready inside the CMS status delivery (CTF-801, ADR-065-R5).

    A database failure propagates, so the outbox retries the whole delivery.
    """
    from ctf.services.range.status import notify_range_ready

    notify_range_ready(participant, publish=publish)


@receiver(range_status_changed)
def sync_ctf_participant_range_status(
    sender: object,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs: object,
) -> None:
    """Update CTFParticipant.range_status when CMS reports a status change."""
    from ctf.models import CTFEvent, CTFParticipant

    participants = CTFParticipant.objects.filter(
        range_instance_id=range_instance_id,
    )
    if new_status == ResourceStatus.READY.value:
        # The range-ready declaration locks the event. Take the event locks first,
        # in primary-key order, as provisioning and recovery do (event before
        # participant); the loop below then reads the assignment under them.
        event_ids = participants.values("event_id")
        list(CTFEvent.objects.select_for_update().filter(pk__in=event_ids).order_by("pk").values_list("pk", flat=True))

    # Scoped provider inventory/readback evidence that every owned resource is
    # gone (#2086, ADR-063-R4/R5). A logical DESTROYED status alone is not proof
    # of absence, so capacity/linkage release waits for this.
    cleanup_verified = bool(kwargs.get("cleanup_verified", False))

    updated = 0
    for participant in participants:
        if new_status == ResourceStatus.DESTROYED.value and cleanup_verified:
            # Verified terminal cleanup: the range's resources are confirmed gone,
            # so return its capacity draw BEFORE dropping the linkage. Propagate
            # failure so durable delivery retries instead of losing the draw key.
            from ctf.bridges import cms_release_range_capacity

            cms_release_range_capacity(participant.pk)
            participant.range_instance_id = None
            participant.range_status = ""
            participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
            updated += 1
        elif participant.range_status != new_status:
            # Any non-verified status -- including DESTROYED without inventory
            # evidence -- retains the participant/range/reservation linkage and
            # capacity until inventory confirms absence (#1919, ADR-063-R5).
            changed_to_ready = new_status == ResourceStatus.READY.value
            participant.range_status = new_status
            participant.save(update_fields=["range_status", "updated_at"])
            updated += 1
            if changed_to_ready:
                _declare_range_ready(participant, publish=True)
        elif new_status == ResourceStatus.READY.value:
            # A status read can cache ``ready`` first; this delivery still
            # declares the notice, and its identity collapses the repeat.
            _declare_range_ready(participant, publish=False)

    if updated:
        logger.info(
            "Synced range_status=%s for %d CTF participant(s) (range_instance_id=%s, was=%s)",
            new_status,
            updated,
            range_instance_id,
            previous_status,
        )


@receiver(range_status_changed)
def sync_ctf_spare_range_status(
    sender: None,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs: object,
) -> None:
    """Update CTFSpareRange.status when CMS reports a status change (#1018).

    This is the "existing event projection" that a spare's status uses to
    reach ``ready``/``failed`` -- no separate polling loop is introduced for
    the spare pool. Only unconsumed spares are touched: once a spare is
    consumed, its range belongs to the participant and further status
    changes are the participant-range projection's concern
    (:func:`sync_ctf_participant_range_status`), not the pool's.
    """
    from ctf.enums import SpareRangeStatus
    from ctf.models import CTFSpareRange

    status_map = {
        ResourceStatus.READY.value: SpareRangeStatus.READY.value,
        ResourceStatus.FAILED.value: SpareRangeStatus.FAILED.value,
        ResourceStatus.DESTROYED.value: SpareRangeStatus.FAILED.value,
    }
    mapped_status = status_map.get(new_status)
    if mapped_status is None:
        return

    spares = CTFSpareRange.objects.filter(
        range_instance_id=range_instance_id,
        consumed_by__isnull=True,
    )

    updated = 0
    for spare in spares:
        if spare.status != mapped_status:
            spare.status = mapped_status
            spare.save(update_fields=["status", "updated_at"])
            updated += 1

    if updated:
        logger.info(
            "Synced spare status=%s for %d CTF spare range(s) (range_instance_id=%s, was=%s)",
            mapped_status,
            updated,
            range_instance_id,
            previous_status,
        )


# ---------------------------------------------------------------------------
# Organizer content images (#2090, ADR-036)
# ---------------------------------------------------------------------------

# Fields whose change can add or remove an external image reference. A save
# that names other update_fields cannot change the event's image set.
_CONTENT_IMAGE_FIELDS: dict[type[Model], frozenset[str]] = {
    CTFEvent: frozenset({"logo_url", "rules"}),
    CTFChallenge: frozenset({"description", "solution", "deleted_at", "event"}),
    CTFEventPage: frozenset({"body", "slug", "deleted_at", "event"}),
    CTFNotification: frozenset({"body", "notification_type", "deleted_at", "event"}),
}


@receiver(post_save, sender=CTFEvent, dispatch_uid="ctf.content_images.event")
@receiver(post_save, sender=CTFChallenge, dispatch_uid="ctf.content_images.challenge")
@receiver(post_save, sender=CTFEventPage, dispatch_uid="ctf.content_images.page")
@receiver(post_save, sender=CTFNotification, dispatch_uid="ctf.content_images.notification")
def sync_content_images_on_save(
    sender: type[Model], instance: Model, update_fields: frozenset[str] | None = None, **kwargs: object
) -> None:
    """After commit, sync the event's image copies with its saved content."""
    if update_fields is not None and not (set(update_fields) & _CONTENT_IMAGE_FIELDS[sender]):
        return
    event_id = instance.pk if sender is CTFEvent else getattr(instance, "event_id", None)
    if event_id is None:
        return
    from ctf.services.content_images import sync_event_content_images

    transaction.on_commit(partial(sync_event_content_images, event_id))
