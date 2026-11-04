"""Real PostgreSQL publication races retain one immutable custody receipt."""

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from cms.models import TrialArchiveReceipt, TrialArchiveTransfer
from cms.services import intake_trial_archive, purge_trial_archives
from shared.exceptions import CMSError
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody
from tests.shared.raes.test_trial_archive import archive_bytes, expected

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_delivery_has_one_receipt_without_overwrite(custody, monkeypatch, different):
    actor, organization, storage = custody
    barrier = threading.Barrier(2, timeout=20)
    original = storage.upload_file

    def overlapping_upload(file_obj, bucket, key, content_type=""):
        original(file_obj, bucket, key, content_type)
        barrier.wait()

    monkeypatch.setattr(storage, "upload_file", overlapping_upload)
    raw = archive_bytes()
    other = archive_bytes(extra={"traces/second.bin": b"another original artifact"}) if different else raw

    def deliver(payload):
        close_old_connections()
        try:
            return intake_trial_archive(actor.credential, organization.uuid, expected(), io.BytesIO(payload))
        except CMSError as error:
            return error
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(deliver, (raw, other)))
    assert TrialArchiveReceipt.objects.count() == 1
    assert TrialArchiveTransfer.objects.count() == 2
    assert len(storage.objects) == 2
    if different:
        assert sum(isinstance(result, CMSError) for result in results) == 1
        assert any("conflict" in str(result) for result in results if isinstance(result, CMSError))
    else:
        assert all(not isinstance(result, Exception) for result in results)
        assert results[0].id == results[1].id
        past = timezone.now() - timedelta(days=31)
        TrialArchiveReceipt.objects.update(expires_at=past)
        TrialArchiveTransfer.objects.update(created_at=past, expires_at=past)
        assert purge_trial_archives(actor.credential, organization.uuid) == 2
        assert not storage.objects
