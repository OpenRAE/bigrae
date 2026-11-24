"""Post-commit CTF delivery: retained linkage on failure and replayed effects."""

import pytest
from django.db import OperationalError, connection
from django.utils import timezone

from cms.handlers.ctf_bridge import drain_ctf_status_deliveries, notify_ctf_range_status
from cms.models import RangeStatusDelivery
from cms.signals import range_status_changed
from ctf.models import CTFSpareRange

pytestmark = pytest.mark.django_db


def test_capacity_release_failure_retains_participant_linkage_for_retry(
    ctf_participant, django_capture_on_commit_callbacks
):
    ctf_participant.range_instance_id = 12345
    ctf_participant.range_status = "destroying"
    ctf_participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])

    def unavailable_capacity(execute, sql, params, many, context):
        if "engine_capacity_draw" in sql:
            raise OperationalError("SYNTHETIC_DATABASE_DETAIL")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable_capacity), django_capture_on_commit_callbacks(execute=True):
        notify_ctf_range_status(12345, "destroyed", "destroying", cleanup_verified=True)

    ctf_participant.refresh_from_db()
    assert ctf_participant.range_instance_id == 12345
    assert ctf_participant.range_status == "destroying"
    delivery = RangeStatusDelivery.objects.get()
    assert delivery.last_error_type == "OperationalError"
    RangeStatusDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now())
    assert drain_ctf_status_deliveries() == 1
    ctf_participant.refresh_from_db()
    assert ctf_participant.range_instance_id is None
    assert ctf_participant.range_status == ""


def test_spare_update_rolls_back_with_later_receiver_failure_and_replays(ctf_event, django_capture_on_commit_callbacks):
    spare = CTFSpareRange.objects.create(event=ctf_event, range_instance_id=12345)

    def unavailable_receiver(sender, **kwargs):
        raise OperationalError("SYNTHETIC_DATABASE_DETAIL")

    range_status_changed.connect(unavailable_receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            notify_ctf_range_status(12345, "ready", "provisioning")
    finally:
        range_status_changed.disconnect(unavailable_receiver)

    spare.refresh_from_db()
    assert spare.status == "provisioning"
    assert RangeStatusDelivery.objects.get().last_error_type == "OperationalError"
    RangeStatusDelivery.objects.update(next_attempt_at=timezone.now())
    assert drain_ctf_status_deliveries() == 1
    spare.refresh_from_db()
    assert spare.status == "ready"
    assert not RangeStatusDelivery.objects.exists()


def test_committed_delivery_applies_each_ctf_side_effect(
    ctf_event, ctf_participant, django_capture_on_commit_callbacks
):
    ctf_participant.range_instance_id = 12345
    ctf_participant.range_status = "provisioning"
    ctf_participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
    spare = CTFSpareRange.objects.create(event=ctf_event, range_instance_id=12346)

    with django_capture_on_commit_callbacks(execute=True):
        notify_ctf_range_status(12345, "paused", "provisioning")
        notify_ctf_range_status(12346, "ready", "provisioning")
        ctf_participant.refresh_from_db()
        assert ctf_participant.range_status == "provisioning"

    ctf_participant.refresh_from_db()
    spare.refresh_from_db()
    assert ctf_participant.range_status == "paused"
    assert spare.status == "ready"

    with django_capture_on_commit_callbacks(execute=True):
        notify_ctf_range_status(12345, "destroyed", "destroying", cleanup_verified=True)

    ctf_participant.refresh_from_db()
    assert ctf_participant.range_instance_id is None
    assert ctf_participant.range_status == ""
    assert not RangeStatusDelivery.objects.exists()


def test_late_destroy_does_not_unlink_a_repointed_participant(ctf_participant, django_capture_on_commit_callbacks):
    ctf_participant.range_instance_id = 12345
    ctf_participant.save(update_fields=["range_instance_id", "updated_at"])
    RangeStatusDelivery.objects.create(
        range_instance_id=12345, new_status="destroyed", previous_status="destroying", cleanup_verified=True
    )
    # Recovery repoints the participant before the retained delivery runs.
    ctf_participant.range_instance_id = 99999
    ctf_participant.range_status = "provisioning"
    ctf_participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])

    assert drain_ctf_status_deliveries() == 1

    ctf_participant.refresh_from_db()
    assert ctf_participant.range_instance_id == 99999
    assert ctf_participant.range_status == "provisioning"
