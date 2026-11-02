"""Named files retain native upload custody and cannot replace admitted bytes."""

import hashlib

import pytest

from cms.exceptions import CMSError
from tests.cms.services.test_principal_uploads import content_actor, content_administrator, storage_client

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]
__all__ = ["content_actor", "content_administrator", "storage_client"]


def _object(client, material):
    client.head_object.return_value = {"ContentLength": len(material), "ETag": '"synthetic-file-version"'}
    client.get_object.return_value["Body"].read.return_value = material


def _upload(actor, client, *, name="parameters", material=b"opaque parameters\n", replaces=None):
    from cms.services import complete_file_upload, initiate_file_upload

    _object(client, material)
    issued = initiate_file_upload(
        actor.credential, name, "parameters.json", len(material), scope=actor.scope, replaces=replaces
    )
    return complete_file_upload(actor.credential, issued["upload_token"])


def test_file_upload_hashes_exact_installed_bytes_and_lists_metadata(content_administrator, storage_client):
    from cms.models import AgentUpload, NamedFileAsset
    from cms.services import complete_file_upload, list_file_assets

    actor = content_administrator
    material = b"opaque\x00synthetic\xffbytes\n"
    asset = _upload(actor, storage_client, material=material)
    admission = AgentUpload.objects.get()
    assert asset.owner_principal_uuid == actor.credential.principal.uuid
    assert asset.account_uuid == actor.scope.account_uuid
    assert asset.sha256_hash == hashlib.sha256(material).hexdigest()
    assert asset.s3_key == admission.install_key
    assert admission.asset_kind == "file"
    assert admission.file_asset_id == asset.pk
    assert admission.os_slug == admission.agent_type == ""
    assert asset.file_size_bytes == len(material)
    assert storage_client.get_object.call_args.kwargs["IfMatch"] == "synthetic-file-version"
    assert storage_client.copy_object.call_args.kwargs["CopySourceIfMatch"] == "synthetic-file-version"
    projection = list_file_assets(actor.credential, scope=actor.scope)
    assert [row["id"] for row in projection] == [asset.pk]
    assert asset.s3_key not in repr(projection)
    assert material.decode("latin1") not in repr(projection)
    from cms.assets.upload_token import generate_scoped_upload_token

    assert complete_file_upload(actor.credential, generate_scoped_upload_token(admission)).pk == asset.pk
    assert NamedFileAsset.objects.count() == 1


def test_file_upload_refuses_other_scope_and_revoked_proof(content_administrator, storage_client):
    from cms.services import complete_file_upload, initiate_file_upload
    from management.models import ServiceCredentialAdmission

    actor = content_administrator
    issued = initiate_file_upload(actor.credential, "parameters", "parameters.json", 20, scope=actor.scope)
    ServiceCredentialAdmission.objects.filter(uuid=actor.credential.credential_uuid).update(is_active=False)
    with pytest.raises(CMSError):
        complete_file_upload(actor.credential, issued["upload_token"])
    storage_client.head_object.assert_not_called()


@pytest.mark.parametrize("size", [0, True, -1, 512 * 1024 + 1])
def test_file_upload_bounds_apply_before_provider_access(content_administrator, storage_client, size):
    from cms.services import initiate_file_upload

    actor = content_administrator
    with pytest.raises(CMSError):
        initiate_file_upload(actor.credential, "parameters", "parameters.json", size, scope=actor.scope)
    storage_client.generate_presigned_url.assert_not_called()


def test_file_and_installer_tokens_cannot_cross_finalize(content_administrator, storage_client):
    from cms.services import complete_file_upload, complete_upload, initiate_file_upload, initiate_upload

    actor = content_administrator
    file = initiate_file_upload(actor.credential, "parameters", "parameters.json", 20, scope=actor.scope)
    installer = initiate_upload(actor.credential, "installer", "installer.msi", 20, scope=actor.scope)
    with pytest.raises(CMSError):
        complete_upload(actor.credential, file["upload_token"])
    with pytest.raises(CMSError):
        complete_file_upload(actor.credential, installer["upload_token"])
    storage_client.head_object.assert_not_called()


def test_replacement_retires_previous_version_without_changing_its_identity(content_administrator, storage_client):
    from cms.models import NamedFileAsset
    from cms.services import list_file_assets

    actor = content_administrator
    old = _upload(actor, storage_client, material=b"first version")
    newer = _upload(actor, storage_client, material=b"second version", replaces=old.pk)
    assert old.pk != newer.pk
    assert old.asset_uuid == newer.asset_uuid
    assert old.s3_key != newer.s3_key
    old.refresh_from_db()
    assert old.deleted_at is not None
    assert old.sha256_hash == hashlib.sha256(b"first version").hexdigest()
    assert [row["id"] for row in list_file_assets(actor.credential, scope=actor.scope)] == [newer.pk]
    assert NamedFileAsset.all_objects.count() == 2


def test_concurrent_replacement_cannot_overwrite_newer_asset(content_administrator, storage_client):
    from cms.services import complete_file_upload, initiate_file_upload, list_file_assets

    actor = content_administrator
    old = _upload(actor, storage_client, material=b"first")
    first = initiate_file_upload(
        actor.credential, "parameters", "parameters.json", 6, scope=actor.scope, replaces=old.pk
    )
    stale = initiate_file_upload(
        actor.credential, "parameters", "parameters.json", 6, scope=actor.scope, replaces=old.pk
    )
    _object(storage_client, b"second")
    installed = complete_file_upload(actor.credential, first["upload_token"])
    with pytest.raises(CMSError):
        complete_file_upload(actor.credential, stale["upload_token"])
    assert [row["id"] for row in list_file_assets(actor.credential, scope=actor.scope)] == [installed.pk]


def test_file_retirement_is_scoped_and_queues_exact_storage_cleanup(content_administrator, storage_client):
    from cms.models import AgentUpload
    from cms.services import delete_file_asset, list_file_assets

    actor = content_administrator
    asset = _upload(actor, storage_client)
    delete_file_asset(actor.credential, asset.pk)
    asset.refresh_from_db()
    assert asset.deleted_at is not None
    assert list_file_assets(actor.credential, scope=actor.scope) == []
    assert AgentUpload.objects.get(file_asset_id=asset.pk).cleanup_pending
    storage_client.delete_object.assert_not_called()


@pytest.mark.parametrize("field", ["asset_kind", "file_owner_uuid", "replaces_file_id", "validated_sha256"])
def test_file_upload_custody_cannot_be_changed_by_bulk_write(content_administrator, storage_client, field):
    from uuid import uuid4

    from django.db import IntegrityError, transaction

    from cms.models import AgentUpload

    asset = _upload(content_administrator, storage_client)
    admission = AgentUpload.objects.get(file_asset=asset)
    values = {
        "asset_kind": "agent",
        "file_owner_uuid": uuid4(),
        "replaces_file_id": asset.pk,
        "validated_sha256": "f" * 64,
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        AgentUpload.objects.filter(pk=admission.pk).update(**{field: values[field]})


@pytest.mark.parametrize("field", ["s3_key", "sha256_hash", "object_identity", "owner_principal_uuid"])
def test_installed_file_custody_cannot_be_changed_by_bulk_write(content_administrator, storage_client, field):
    from uuid import uuid4

    from django.db import IntegrityError, transaction

    from cms.models import NamedFileAsset

    asset = _upload(content_administrator, storage_client)
    values = {
        "s3_key": "unadmitted/other-object",
        "sha256_hash": "f" * 64,
        "object_identity": {"etag": "unadmitted-object"},
        "owner_principal_uuid": uuid4(),
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        NamedFileAsset.objects.filter(pk=asset.pk).update(**{field: values[field]})


def test_file_upload_rejects_foreign_scope_before_issuing_a_capability(content_administrator, storage_client):
    from cms.services import initiate_file_upload, list_file_assets

    actor = content_administrator
    with pytest.raises(CMSError):
        initiate_file_upload(actor.credential, "parameters", "parameters.json", 10, scope=actor.sibling)
    with pytest.raises(CMSError):
        list_file_assets(actor.credential, scope=actor.sibling)
    storage_client.generate_presigned_url.assert_not_called()


def test_file_quota_counts_retired_bytes_until_storage_cleanup(content_administrator, storage_client, monkeypatch):
    from datetime import timedelta

    from cms.models import AgentUpload
    from cms.services import get_storage_used, initiate_file_upload
    from cms.services._scoped_uploads import reconcile_upload_cleanup

    actor = content_administrator
    original = _upload(actor, storage_client, material=b"x" * 400_000)
    _upload(actor, storage_client, material=b"y" * 400_000, replaces=original.pk)
    assert get_storage_used(actor.credential, scope=actor.scope) == 800_000
    with pytest.raises(CMSError):
        initiate_file_upload(actor.credential, "second", "other.bin", 400_000, scope=actor.scope)
    latest_expiry = AgentUpload.objects.latest("expires_at").expires_at
    monkeypatch.setattr("cms.services._upload_cleanup.timezone.now", lambda: latest_expiry + timedelta(seconds=1))
    assert reconcile_upload_cleanup() == 2
    assert get_storage_used(actor.credential, scope=actor.scope) == 400_000
    initiate_file_upload(actor.credential, "second", "other.bin", 400_000, scope=actor.scope)


def test_range_use_retains_retired_file_until_confirmed_destruction(content_administrator, storage_client, monkeypatch):
    from datetime import timedelta

    from cms.models import AgentUpload, FileAssetUse, RangeInstance
    from cms.services import delete_file_asset, get_storage_used
    from cms.services._scoped_uploads import reconcile_upload_cleanup
    from workspaces.services import resolve_resource_scope

    actor = content_administrator
    asset = _upload(actor, storage_client)
    account = resolve_resource_scope(actor.scope)
    instance = RangeInstance.objects.create(
        scenario_id="synthetic",
        status="ready",
        scope_kind="account",
        account_id=account.account_id,
        owner_principal_uuid=actor.credential.principal.uuid,
    )
    FileAssetUse.objects.create(file_asset=asset, range_instance=instance, input_name="parameters")
    delete_file_asset(actor.credential, asset.pk)
    admission = AgentUpload.objects.get(file_asset=asset)
    clock = admission.expires_at + timedelta(seconds=1)
    monkeypatch.setattr("cms.services._upload_cleanup.timezone.now", lambda: clock)
    assert reconcile_upload_cleanup() == 1
    deleted = [call.kwargs["Key"] for call in storage_client.delete_object.call_args_list]
    assert asset.s3_key not in deleted
    assert get_storage_used(actor.credential, scope=actor.scope) == asset.file_size_bytes

    instance.status = "destroyed"
    instance.save(update_fields=["status"])
    clock += timedelta(minutes=16)
    assert reconcile_upload_cleanup() == 1
    assert asset.s3_key in [call.kwargs["Key"] for call in storage_client.delete_object.call_args_list]
    assert get_storage_used(actor.credential, scope=actor.scope) == 0
    asset.refresh_from_db()
    deleted_at = asset.storage_deleted_at
    clock += timedelta(minutes=16)
    assert reconcile_upload_cleanup() == 1
    asset.refresh_from_db()
    assert asset.storage_deleted_at == deleted_at
