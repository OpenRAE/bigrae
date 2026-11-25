"""Durable local signal delivery: commit boundary, ordered retry and source retention."""

import logging
from datetime import timedelta

import pytest
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from cms.handlers.ctf_bridge import ctf_status_delivery_backlog, drain_ctf_status_deliveries, notify_ctf_range_status
from cms.models import RangeStatusDelivery
from cms.signals import range_status_changed

pytestmark = pytest.mark.django_db


def test_failed_delivery_does_not_overtake_earlier_status_or_lose_cleanup_proof(
    caplog, django_capture_on_commit_callbacks
):
    observed = []
    unavailable = True

    def receiver(sender, new_status, cleanup_verified, **kwargs):
        observed.append((new_status, cleanup_verified))
        if unavailable:
            raise RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_TEXT")

    range_status_changed.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            notify_ctf_range_status(12345, "ready", "provisioning")
            notify_ctf_range_status(12345, "destroyed", "destroying", cleanup_verified=True)
            assert observed == []
        # Both post-commit attempts stop at the failed head; neither overtakes it.
        assert observed == [("ready", False)]
        assert RangeStatusDelivery.objects.count() == 2
        assert "SYNTHETIC_PRIVATE_PROVIDER_TEXT" not in caplog.text
        unavailable = False
        RangeStatusDelivery.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        assert drain_ctf_status_deliveries(limit=1) == 1
        assert drain_ctf_status_deliveries() == 1
        assert observed == [("ready", False), ("ready", False), ("destroyed", True)]
        assert not RangeStatusDelivery.objects.exists()
        assert drain_ctf_status_deliveries() == 0
    finally:
        range_status_changed.disconnect(receiver)


def test_delivery_is_not_created_or_attempted_when_the_owning_transaction_rolls_back(
    django_capture_on_commit_callbacks,
):
    observed = []

    def receiver(sender, **kwargs):
        observed.append(kwargs)

    range_status_changed.connect(receiver, weak=False)
    try:
        with (
            django_capture_on_commit_callbacks(execute=True) as callbacks,
            pytest.raises(ValueError, match="abort"),
            transaction.atomic(),
        ):
            notify_ctf_range_status(12345, "ready", "provisioning")
            assert RangeStatusDelivery.objects.count() == 1
            raise ValueError("abort")
    finally:
        range_status_changed.disconnect(receiver)
    assert callbacks == []
    assert observed == []
    assert not RangeStatusDelivery.objects.exists()


def test_failed_range_does_not_block_delivery_to_another_range(django_capture_on_commit_callbacks):
    def receiver(sender, range_instance_id, **kwargs):
        if range_instance_id == 12345:
            raise RuntimeError("unavailable")

    range_status_changed.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            notify_ctf_range_status(12345, "ready", "provisioning")
            notify_ctf_range_status(12346, "ready", "provisioning")
    finally:
        range_status_changed.disconnect(receiver)
    assert list(RangeStatusDelivery.objects.values_list("range_instance_id", flat=True)) == [12345]


def test_post_commit_attempt_failure_keeps_the_delivery_and_logs_only_the_class(
    caplog, django_capture_on_commit_callbacks
):
    def unavailable_delivery_read(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("SELECT") and "cms_rangestatusdelivery" in sql:
            raise OperationalError("SYNTHETIC_PRIVATE_DATABASE_TEXT")
        return execute(sql, params, many, context)

    with django_capture_on_commit_callbacks() as callbacks:
        notify_ctf_range_status(12345, "ready", "provisioning")
    assert len(callbacks) == 1
    # Only the post-commit attempt meets the database outage.
    with (
        caplog.at_level(logging.ERROR, logger="cms.handlers.ctf_bridge"),
        connection.execute_wrapper(unavailable_delivery_read),
    ):
        callbacks[0]()

    assert RangeStatusDelivery.objects.get().range_instance_id == 12345
    deferred = [r for r in caplog.records if "deferred to reconciler" in r.getMessage()]
    assert len(deferred) == 1
    assert not deferred[0].exc_info
    assert "exc_type=OperationalError" in deferred[0].getMessage()
    assert "SYNTHETIC_PRIVATE_DATABASE_TEXT" not in caplog.text


def test_backlog_reports_pending_retrying_and_oldest_age():
    assert ctf_status_delivery_backlog() == {"pending": 0, "retrying": 0, "oldest_age_seconds": 0}
    old = RangeStatusDelivery.objects.create(
        range_instance_id=12345, new_status="ready", previous_status="provisioning"
    )
    RangeStatusDelivery.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=10), attempts=3)
    RangeStatusDelivery.objects.create(range_instance_id=12346, new_status="ready", previous_status="provisioning")

    backlog = ctf_status_delivery_backlog()

    assert backlog["pending"] == 2
    assert backlog["retrying"] == 1
    assert 600 <= backlog["oldest_age_seconds"] < 660


def test_backed_off_range_does_not_fill_the_retry_batch():
    for index in range(3):
        RangeStatusDelivery.objects.create(
            range_instance_id=12345,
            new_status="ready",
            previous_status="provisioning",
            next_attempt_at=timezone.now() + timedelta(minutes=5) if index == 0 else timezone.now(),
        )
    RangeStatusDelivery.objects.create(range_instance_id=12346, new_status="ready", previous_status="provisioning")

    assert drain_ctf_status_deliveries(limit=1) == 1
    assert set(RangeStatusDelivery.objects.values_list("range_instance_id", flat=True)) == {12345}
