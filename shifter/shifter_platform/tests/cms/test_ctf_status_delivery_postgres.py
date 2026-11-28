"""PostgreSQL proof that CTF delivery never holds the CMS status write (#2577).

SQLite cannot prove row locks or commit visibility across connections.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from cms.handlers.ctf_bridge import drain_ctf_status_deliveries
from cms.handlers.range_events import apply_range_status
from cms.models import RangeInstance, RangeStatusDelivery
from cms.models import Request as CMSRequest
from cms.signals import range_status_changed
from shared.enums import RequestType, ResourceStatus

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _range_instance(status: str) -> RangeInstance:
    user = get_user_model().objects.create_user(username="delivery@e.com", email="delivery@e.com")
    request = CMSRequest.objects.create(
        workspace_id=1, request_id=uuid4(), request_type=RequestType.RANGE.value, user=user
    )
    return RangeInstance.objects.create(
        workspace_id=1, user_id=user.id, request=request, status=status, scenario_id="basic"
    )


def test_cms_status_write_commits_while_a_ctf_receiver_is_blocked():
    instance = _range_instance(ResourceStatus.PROVISIONING.value)
    RangeStatusDelivery.objects.create(
        range_instance_id=instance.pk,
        new_status=ResourceStatus.PROVISIONING.value,
        previous_status=ResourceStatus.PENDING.value,
    )
    receiver_entered = threading.Event()
    cms_committed = threading.Event()
    waits: list[bool] = []

    def blocked_receiver(sender, **kwargs):
        receiver_entered.set()
        # A CMS projection lock held here would keep the status write waiting.
        waits.append(cms_committed.wait(timeout=10))

    def blocked_delivery():
        try:
            return drain_ctf_status_deliveries(range_instance_id=instance.pk)
        finally:
            connection.close()

    def cms_status_write():
        try:
            assert receiver_entered.wait(timeout=10)
            with transaction.atomic():
                # Registered first, so it fires on commit before the delivery attempt.
                transaction.on_commit(cms_committed.set)
                return apply_range_status(RangeInstance.all_objects.get(pk=instance.pk), ResourceStatus.READY.value)
        finally:
            connection.close()

    range_status_changed.connect(blocked_receiver, weak=False)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            delivery = pool.submit(blocked_delivery)
            write = pool.submit(cms_status_write)
            assert write.result(timeout=30) is True
            delivery.result(timeout=30)
    finally:
        range_status_changed.disconnect(blocked_receiver)

    assert waits == [True, True]
    instance.refresh_from_db()
    assert instance.status == ResourceStatus.READY.value
    # Both transitions were delivered in order; nothing is left for retry.
    assert not RangeStatusDelivery.objects.exists()
