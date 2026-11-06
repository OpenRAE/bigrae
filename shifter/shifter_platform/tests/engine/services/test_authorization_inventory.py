"""Delegation inventory uses the public CMS range policy identity."""

from uuid import uuid4

import pytest

from engine.models import Range
from engine.services._authorization_inventory import (
    _authorization_event_range_targets,
    _authorization_range_binding,
    list_authorization_range_uuids,
)
from shared.authorization import TargetRef
from shared.authorization.inventory import AuthorizationDescendantResolutionError
from shared.identity_scope import ResourceScope
from tests.cms.services.test_principal_range_authority import principal_range

__all__ = ["principal_range"]

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def test_workspace_range_inventory_returns_public_policy_uuid():
    public_uuid, native_uuid = uuid4(), uuid4()
    Range.objects.create(
        uuid=native_uuid,
        cms_range_uuid=public_uuid,
        scope_kind="account",
        account_id=101,
        organization_id=102,
        workspace_id=103,
    )
    result = list_authorization_range_uuids((103,), 10)
    assert result == (public_uuid,)
    assert native_uuid not in result


@pytest.mark.parametrize("status", ["destroying", "destroyed"])
def test_retiring_workspace_ranges_do_not_consume_the_inventory_limit(status):
    Range.objects.create(workspace_id=103, status=status, cms_range_uuid=None)
    live = Range.objects.create(workspace_id=103, status="ready", cms_range_uuid=uuid4())
    assert list_authorization_range_uuids((103,), 1) == (live.cms_range_uuid,)
    assert Range.objects.count() == 2


@pytest.mark.parametrize("status", ["destroying", "destroyed"])
def test_retiring_event_ranges_do_not_need_live_ancestry(status):
    event_uuid = uuid4()
    Range.objects.create(
        event_uuid=event_uuid, status=status, request=None, scope_kind="account", account_id=101, organization_id=102
    )
    assert _authorization_event_range_targets(event_uuid, 1) == ()
    assert Range.objects.count() == 1


def test_live_workspace_range_with_missing_public_identity_still_fails_closed():
    Range.objects.create(workspace_id=103, status="ready", cms_range_uuid=None)
    with pytest.raises(AuthorizationDescendantResolutionError):
        list_authorization_range_uuids((103,), 1)


def test_live_event_range_with_missing_request_still_fails_closed():
    event_uuid = uuid4()
    Range.objects.create(
        event_uuid=event_uuid, status="ready", request=None, scope_kind="account", account_id=101, organization_id=102
    )
    with pytest.raises(AuthorizationDescendantResolutionError):
        _authorization_event_range_targets(event_uuid, 1)


@pytest.mark.parametrize("status", ["destroying", "destroyed"])
def test_direct_binding_of_a_retained_range_is_unchanged(principal_range, status):
    row = principal_range.realized
    row.status = status
    row.save(update_fields=["status"])
    parent, scope = _authorization_range_binding(row.cms_range_uuid)
    assert parent == TargetRef("account", principal_range.account.uuid)
    assert scope == ResourceScope("account", principal_range.account.uuid)
    row.refresh_from_db()
    assert row.status == status
    assert row.owner_principal_uuid == principal_range.owner.uuid
