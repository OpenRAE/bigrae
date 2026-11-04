"""File APIs drive native custody; cloud calls are the only mocked boundary."""

import json
from unittest.mock import MagicMock

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def _url(name, **kwargs):
    return reverse(f"v1:mission_control:{name}", kwargs=kwargs)


def _post(client, name, payload):
    return client.post(_url(name), data=json.dumps(payload), content_type="application/json")


@pytest.fixture
def file_storage(settings, monkeypatch):
    settings.CLOUD_PROVIDER = "aws"
    settings.AWS_S3_BUCKET_NAME = "synthetic-file-assets"
    storage = MagicMock()
    storage.generate_presigned_url.return_value = "https://storage.example.test/upload-capability"
    storage.head_object.return_value = {"ContentLength": 4, "ETag": '"file-version"'}
    storage.get_object.return_value["Body"].read.return_value = b"data"
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: storage)
    return storage


def _upload(client, *, replaces=None):
    payload = {"name": "parameters", "filename": "parameters.json", "file_size": 4}
    if replaces is not None:
        payload["replaces"] = replaces
    issued = _post(client, "file-upload-initiate", payload)
    assert issued.status_code == 200, issued.content
    complete = _post(client, "file-upload-complete", {"upload_token": issued.json()["upload_token"]})
    assert complete.status_code == 200, complete.content
    return complete.json()["file_id"]


def test_file_api_upload_list_replace_and_delete(authenticated_client, file_storage):
    from cms.models import NamedFileAsset

    client, _ = authenticated_client(email="files@example.test")
    original = _upload(client)
    result = client.get(_url("files-list"))
    assert result.status_code == 200
    assert result.json()["max_file_size_bytes"] == 512 * 1024
    assert [row["id"] for row in result.json()["files"]] == [original]
    assert "s3_key" not in result.json()["files"][0]
    assert "sha256" not in result.content.decode()
    newer = _upload(client, replaces=original)
    assert newer != original
    assert NamedFileAsset.all_objects.get(pk=original).deleted_at is not None
    assert [row["id"] for row in client.get(_url("files-list")).json()["files"]] == [newer]
    assert client.delete(_url("files-detail", file_id=newer)).status_code == 200
    assert client.get(_url("files-list")).json()["files"] == []


@pytest.mark.parametrize("method,name", [("get", "files-list"), ("post", "file-upload-initiate")])
def test_file_api_requires_native_authentication(method, name):
    assert getattr(Client(), method)(_url(name)).status_code == 401


@pytest.mark.parametrize("changed", ["bool-size", "oversize", "authority", "kind"])
def test_file_upload_validation_cannot_issue_an_unbound_capability(authenticated_client, file_storage, changed):
    client, _ = authenticated_client(email="file-validation@example.test")
    payload = {"name": "parameters", "filename": "parameters.json", "file_size": 4}
    if changed in {"bool-size", "oversize"}:
        payload["file_size"] = True if changed == "bool-size" else 512 * 1024 + 1
    else:
        payload["owner_principal_uuid" if changed == "authority" else "asset_kind"] = "untrusted"
    assert _post(client, "file-upload-initiate", payload).status_code == 400
    file_storage.generate_presigned_url.assert_not_called()


def test_file_list_rejects_malformed_scope(authenticated_client, file_storage):
    client, _ = authenticated_client(email="file-scope@example.test")
    assert client.get(_url("files-list"), {"workspace_uuid": "invalid"}).status_code == 400
    file_storage.head_object.assert_not_called()


def test_file_upload_cancellation_retains_native_cleanup_record(authenticated_client, file_storage):
    from cms.models import AgentUpload

    client, _ = authenticated_client(email="file-cancel@example.test")
    issued = _post(client, "file-upload-initiate", {"name": "parameters", "filename": "p.bin", "file_size": 4})
    assert issued.status_code == 200
    result = _post(client, "file-upload-cancel", {"upload_token": issued.json()["upload_token"]})
    assert result.status_code == 200
    admission = AgentUpload.objects.get()
    assert admission.state == "cancelled"
    assert admission.cleanup_pending
    assert "upload_lock" not in client.session
