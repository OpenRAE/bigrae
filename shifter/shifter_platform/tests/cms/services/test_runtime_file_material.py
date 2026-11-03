"""Original file authority, bounded bytes and retained versions govern dispatch."""

from uuid import uuid4

import pytest
from django.db import transaction

from cms.exceptions import CMSError
from cms.models import FileAssetUse, RangeInstance, Request
from cms.services import delete_file_asset, load_runtime_file_inputs
from cms.services._runtime_file_admission import pin_runtime_file_uses, prepare_file_selection
from tests.cms.services.test_file_assets import _object, _upload
from tests.cms.services.test_principal_uploads import content_actor, content_administrator, storage_client
from workspaces.services import resolve_resource_scope

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]
__all__ = ["content_actor", "content_administrator", "storage_client"]


def _instance(actor, *, source="mission_control"):
    resolved = resolve_resource_scope(actor.scope)
    fields = {
        "scope_kind": resolved.kind,
        "account_id": resolved.account_id,
        "organization_id": resolved.organization_id,
        "workspace_id": resolved.workspace_id,
        "owner_principal_uuid": actor.credential.principal.uuid,
    }
    request = Request.objects.create(request_id=uuid4(), request_type="range", **fields)
    return RangeInstance.objects.create(
        request=request, scenario_id="synthetic", status="provisioning", range_source=source, **fields
    )


def _pin(actor, asset):
    instance = _instance(actor)
    files = prepare_file_selection(actor.credential, actor.scope, {"parameters": asset.asset_uuid})
    with transaction.atomic():
        pin_runtime_file_uses(actor.credential, actor.scope, instance, files)
        instance.range_id = 123
        instance.save(update_fields=["range_id"])
    return instance, files


def test_retained_material_uses_admitted_version_after_replacement(content_administrator, storage_client):
    actor = content_administrator
    old = _upload(actor, storage_client, material=b"first")
    instance, files = _pin(actor, old)
    newer = _upload(actor, storage_client, material=b"second", replaces=old.pk)
    _object(storage_client, b"first")
    assert load_runtime_file_inputs(instance.request.request_id, files) == {"parameters": b"first"}
    assert storage_client.get_object.call_args.kwargs["Key"] == old.s3_key
    next_files = prepare_file_selection(actor.credential, actor.scope, {"parameters": old.asset_uuid})
    assert next_files["parameters"].version_id == newer.pk
    assert FileAssetUse.objects.get().credential_uuid == actor.credential.credential_uuid


def test_missing_deleted_or_foreign_file_cannot_be_admitted(content_administrator, storage_client):
    actor = content_administrator
    asset = _upload(actor, storage_client)
    with pytest.raises(CMSError):
        prepare_file_selection(actor.credential, actor.sibling, {"parameters": asset.asset_uuid})
    with pytest.raises(CMSError):
        prepare_file_selection(actor.credential, actor.scope, {"parameters": uuid4()})
    files = prepare_file_selection(actor.credential, actor.scope, {"parameters": asset.asset_uuid})
    instance = _instance(actor)
    delete_file_asset(actor.credential, asset.pk)
    with pytest.raises(CMSError), transaction.atomic():
        pin_runtime_file_uses(actor.credential, actor.scope, instance, files)
    assert not FileAssetUse.objects.exists()


def test_revoked_original_proof_blocks_material_before_storage_read(content_administrator, storage_client):
    from management.models import ServiceCredentialAdmission

    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client))
    storage_client.get_object.reset_mock()
    ServiceCredentialAdmission.objects.filter(uuid=actor.credential.credential_uuid).update(is_active=False)
    with pytest.raises(CMSError):
        load_runtime_file_inputs(instance.request.request_id, files)
    storage_client.get_object.assert_not_called()


@pytest.mark.parametrize("material", [b"wrong", b"first!", b"firs"])
def test_material_digest_and_exact_length_are_verified(content_administrator, storage_client, material):
    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client, material=b"first"))
    _object(storage_client, material)
    with pytest.raises((CMSError, ValueError)):
        load_runtime_file_inputs(instance.request.request_id, files)


def test_revocation_during_storage_read_fails_the_final_fence(content_administrator, storage_client):
    from management.models import ServiceCredentialAdmission

    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client, material=b"first"))

    def read(*_args, **_kwargs):
        ServiceCredentialAdmission.objects.filter(uuid=actor.credential.credential_uuid).update(is_active=False)
        return b"first"

    storage_client.get_object.return_value["Body"].read.side_effect = read
    with pytest.raises(CMSError):
        load_runtime_file_inputs(instance.request.request_id, files)


def test_policy_revocation_during_storage_read_blocks_material(content_administrator, storage_client, monkeypatch):
    from types import SimpleNamespace

    from shared.authorization import AuthorizationDecision, DecisionKind, port

    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client, material=b"first"))

    def read(*_args, **_kwargs):
        monkeypatch.setattr(
            port,
            "_provider_factory",
            lambda: SimpleNamespace(check=lambda _request: AuthorizationDecision(DecisionKind.DENIED, "policy_denied")),
        )
        return b"first"

    storage_client.get_object.return_value["Body"].read.side_effect = read
    with pytest.raises(CMSError):
        load_runtime_file_inputs(instance.request.request_id, files)


def test_file_pin_cannot_be_borrowed_by_another_request_or_rewritten(content_administrator, storage_client):
    from django.db import IntegrityError

    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client))
    other = _instance(actor, source="ctf")
    other.range_id = 456
    other.save(update_fields=["range_id"])
    with pytest.raises(CMSError):
        load_runtime_file_inputs(other.request.request_id, files)
    with pytest.raises(IntegrityError), transaction.atomic():
        FileAssetUse.objects.filter(range_instance=instance).update(range_instance=other)


def test_terminal_range_cannot_supply_material(content_administrator, storage_client):
    actor = content_administrator
    instance, files = _pin(actor, _upload(actor, storage_client))
    RangeInstance.all_objects.filter(pk=instance.pk).update(status="destroyed")
    storage_client.get_object.reset_mock()
    with pytest.raises(CMSError):
        load_runtime_file_inputs(instance.request.request_id, files)
    storage_client.get_object.assert_not_called()
