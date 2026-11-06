"""New native range ancestry is confirmed through the existing provider port."""

from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import connection

from engine.models import Range
from engine.services import publish_range_relationships
from engine.services._range_authority_history import record_range_authority_change
from shared.authorization import HierarchyRelationshipChange, RelationshipState, port
from tests.cms.services.test_principal_range_authority import principal_range

__all__ = ["principal_range"]
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.postgres]


@pytest.fixture
def publication(principal_range, monkeypatch, request):
    actor = principal_range
    if getattr(request, "param", True):
        record_range_authority_change(actor.realized, actor.credential, "create", "")
    actor.relationships = set()
    actor.writes = []

    def write(change):
        assert not connection.in_atomic_block
        actor.writes.append(change)
        actor.relationships.add(change.grant_tuple)

    def read(change):
        assert not connection.in_atomic_block
        return RelationshipState(change.grant_tuple in actor.relationships, False)

    actor.provider = SimpleNamespace(write_relationships=write, read_relationships=read)
    monkeypatch.setattr(port, "_provider_factory", lambda: actor.provider)
    return actor


def test_creation_parent_is_published_and_recovery_is_idempotent(publication):
    actor = publication
    expected = HierarchyRelationshipChange(f"account:{actor.account.uuid}", "account", f"range:{actor.instance.uuid}")
    publish_range_relationships(actor.request.request_id)
    output = StringIO()
    call_command("reconcile_range_authorization", request_id=actor.request.request_id, stdout=output)
    assert actor.writes == [expected, expected]
    assert actor.relationships == {expected.grant_tuple}
    assert "confirmed" in output.getvalue()


def test_write_acknowledgment_loss_is_recovered_by_primary_readback(publication):
    write = publication.provider.write_relationships

    def lost_ack(change):
        write(change)
        raise RuntimeError("PRIVATE_PROVIDER_ERROR")

    publication.provider.write_relationships = lost_ack
    publish_range_relationships(publication.request.request_id)
    assert len(publication.relationships) == 1


def test_missing_readback_does_not_confirm_publication(publication):
    publication.provider.read_relationships = lambda change: RelationshipState(False, False)
    with pytest.raises(ValueError, match=r"^Range authority publication unavailable$"):
        publish_range_relationships(publication.request.request_id)


@pytest.mark.parametrize("publication", [False], indirect=True)
def test_missing_creation_receipt_stops_before_provider_write(publication):
    with pytest.raises(ValueError, match=r"^Range authority publication unavailable$"):
        publish_range_relationships(publication.request.request_id)
    assert not publication.writes


def test_generation_change_during_readback_stops_confirmation(publication):
    read = publication.provider.read_relationships

    def changed_generation(change):
        result = read(change)
        Range.objects.filter(pk=publication.realized.pk).update(resource_generation=uuid4())
        return result

    publication.provider.read_relationships = changed_generation
    with pytest.raises(ValueError, match=r"^Range authority publication unavailable$"):
        publish_range_relationships(publication.request.request_id)
