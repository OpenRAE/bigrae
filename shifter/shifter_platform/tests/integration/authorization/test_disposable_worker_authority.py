"""Native worker custody grants real range authority in the released model."""

import pytest
from openfga_sdk.client.models import ClientTuple

from shared.authorization import port
from tests.engine.services.test_disposable_workers import apparatus, create, tenant
from tests.integration.authorization.test_openfga_released_server import _write_fixture_tuple, provider

__all__ = ["apparatus", "provider", "tenant"]
pytestmark = [pytest.mark.openfga, pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def test_disposable_worker_native_parent_permits_management_in_released_model(apparatus, provider, monkeypatch):
    from engine.models import DisposableWorker
    from engine.services import get_disposable_worker, retire_disposable_worker

    account = apparatus.scope.account_uuid
    for item in (
        ClientTuple("installation:root", "installation", f"account:{account}"),
        ClientTuple(f"principal:{apparatus.credential.principal.uuid}", "direct_administrator", f"account:{account}"),
    ):
        _write_fixture_tuple(provider, item)
    if apparatus.scope.organization_uuid:
        _write_fixture_tuple(
            provider, ClientTuple(f"account:{account}", "account", f"organization:{apparatus.scope.organization_uuid}")
        )
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    worker = create(apparatus)
    row = DisposableWorker.objects.get(pk=worker.worker_id)
    assert row.authorization_publication_state == "confirmed"
    assert row.authorization_provider_store_id == provider.store_id
    assert row.authorization_model_id == provider.model_id
    assert get_disposable_worker(apparatus.credential, worker.worker_id).worker_id == worker.worker_id
    retired = retire_disposable_worker(apparatus.credential, worker.worker_id)
    assert retired.status == "destroying"
