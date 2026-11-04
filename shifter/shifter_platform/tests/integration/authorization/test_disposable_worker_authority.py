"""Native worker custody grants real range authority in the released model."""

import pytest
from openfga_sdk.client.models import ClientTuple

from shared.authorization import port
from tests._worker_cloud import worker_cloud
from tests.engine.services.test_disposable_workers import apparatus, create, tenant
from tests.engine.test_worker_validation_command import operator
from tests.integration.authorization.test_openfga_released_server import _write_fixture_tuple, provider

__all__ = ["apparatus", "operator", "provider", "tenant", "worker_cloud"]
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


def test_recorded_operator_qualifies_workers_with_released_policy(
    apparatus, operator, provider, worker_cloud, monkeypatch
):
    """Exercise actual bootstrap selection, Knox proof and worker services together."""
    import json
    from io import StringIO

    from django.core.management import call_command

    from shared.api_tokens.models import ApiToken
    from workspaces.models import IdentityCutoverState

    account = apparatus.scope.account_uuid
    organization = apparatus.scope.organization_uuid
    principal = apparatus.credential.principal.uuid
    for item in (
        ClientTuple("installation:root", "installation", f"account:{account}"),
        ClientTuple(f"account:{account}", "account", f"organization:{organization}"),
        ClientTuple(f"principal:{principal}", "direct_administrator", "installation:root"),
    ):
        _write_fixture_tuple(provider, item)
    from shared.authorization import PolicyEffect, PolicyRelationshipChange, RelationshipSubject, TargetRef

    provider.write_relationships(
        PolicyRelationshipChange(
            RelationshipSubject("principal", principal),
            "installation.use_personal_tokens",
            TargetRef("installation"),
            PolicyEffect.GRANT,
        )
    )
    IdentityCutoverState.objects.update(provider_store_id=provider.store_id, model_id=provider.model_id)
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    output = StringIO()
    call_command(
        "qualify_disposable_workers",
        bootstrap_facts=str(operator),
        scope_kind="organization",
        scope_id=organization,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["independent_workers"] == 2 and result["cleanup_verified"]
    tokens = list(ApiToken.objects.filter(name="worker-validation"))
    assert len(tokens) == 4 and all(item.revoked_at is not None for item in tokens)
