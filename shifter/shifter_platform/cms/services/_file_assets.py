"""Named file metadata and versions under the incumbent native upload custody."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from shifter_adapter_sdk.runtime import MAX_FILE_INPUT_BYTES

from cms.exceptions import CMSError
from cms.models import AgentUpload, AgentUploadBudget, NamedFileAsset
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields

from ._content_authority import content_scope, content_scope_fields, fence_content_scope, require_content_scope
from ._upload_scope import UploadOptions, bounded_upload_label

if TYPE_CHECKING:
    from typing import Any

    from django.db.models import QuerySet

    from shared.cloud.types import ObjectStorage
    from shared.credentials import CredentialContext
    from shared.identity_scope import ResourceScope
    from shared.schemas.cms_projections import UploadInitiation

_UNAVAILABLE = "File unavailable"


def retained_files() -> QuerySet[NamedFileAsset]:
    """Charge installed bytes until their exact storage cleanup is established."""
    return NamedFileAsset.all_objects.filter(storage_deleted_at__isnull=True)


def file_storage_used(scope: ResourceScope) -> int:
    """Include retired versions still pinned to a live or uncertain range."""
    return retained_files().filter(**content_scope_fields(scope)).aggregate(total=Sum("file_size_bytes"))["total"] or 0


def file_asset_for_action(credential: CredentialContext, identifier: int, action: str) -> NamedFileAsset:
    """Authorize the actual stored scope before revealing metadata or bytes."""
    if type(identifier) is not int or identifier <= 0:
        raise CMSError(_UNAVAILABLE)
    snapshot = NamedFileAsset.objects.filter(pk=identifier).first()
    scope = content_scope(snapshot)
    require_content_scope(credential, scope, action)
    row = NamedFileAsset.objects.filter(
        pk=snapshot.pk,
        owner_principal_uuid=snapshot.owner_principal_uuid,
        scope_generation=snapshot.scope_generation,
        s3_key=snapshot.s3_key,
        **content_scope_fields(scope),
    ).first()
    if row is None:
        raise CMSError(_UNAVAILABLE)
    return row


def file_upload_metadata(
    credential: CredentialContext, scope: ResourceScope, name: str, filename: str, size: int, options: UploadOptions
) -> dict[str, Any]:
    """Bind a replacement to its exact version while preserving its owner."""
    bounded_upload_label(name, 100)
    bounded_upload_label(filename, 255)
    if type(size) is not int or not 0 < size <= MAX_FILE_INPUT_BYTES:
        raise CMSError("File size exceeds the input file limit")
    if scope.kind != "account" or not settings.AWS_S3_BUCKET_NAME:
        raise CMSError(_UNAVAILABLE)
    values: dict[str, Any] = {"file_owner_uuid": credential.principal.uuid}
    if options.replaces is not None:
        previous = file_asset_for_action(credential, options.replaces, "manage_content")
        if content_scope(previous) != scope or previous.name != name.strip():
            raise CMSError(_UNAVAILABLE)
        values.update(
            replaces_file_id=previous.pk,
            replacement_generation=previous.scope_generation,
            file_owner_uuid=previous.owner_principal_uuid,
        )
    return values


def validate_file_object(row: AgentUpload, storage: ObjectStorage, identity: dict[str, Any]) -> str:
    """Hash bounded staged bytes under the same identity the copy must consume."""
    if not 0 < row.file_size <= MAX_FILE_INPUT_BYTES:
        raise CMSError("File size exceeds the input file limit")
    material = storage.read_object_header(
        bucket=row.storage_bucket, key=row.staging_key, max_bytes=row.file_size + 1, expected_identity=identity
    )
    if len(material) != row.file_size:
        raise CMSError("Uploaded file size does not match")
    return hashlib.sha256(material).hexdigest()


def create_uploaded_file(row: AgentUpload, scope: ResourceScope, identity: dict[str, Any]) -> NamedFileAsset:
    """Install the catalog version inside the caller's fenced budget transaction."""
    if type(identity.get("content_length")) is not int or identity["content_length"] != row.file_size:
        raise CMSError("Installed file size does not match")
    version_fields = {}
    if row.replaces_file_id is not None:
        previous = NamedFileAsset.objects.select_for_update().filter(pk=row.replaces_file_id).first()
        if (
            previous is None
            or previous.scope_generation != row.replacement_generation
            or content_scope(previous) != scope
            or previous.owner_principal_uuid != row.file_owner_uuid
            or previous.name != row.name
        ):
            raise CMSError("The file changed; start a new replacement")
        previous.deleted_at = timezone.now()
        previous.save(update_fields=["deleted_at"])
        version_fields["asset_uuid"] = previous.asset_uuid
        AgentUpload.objects.filter(file_asset_id=previous.pk, install_key=previous.s3_key).update(cleanup_pending=True)
    return NamedFileAsset.objects.create(
        user=None,
        owner_principal_uuid=row.file_owner_uuid,
        **content_scope_fields(scope),
        name=row.name,
        s3_key=row.install_key,
        original_filename=row.filename,
        file_size_bytes=row.file_size,
        sha256_hash=row.validated_sha256,
        storage_provider=row.storage_provider,
        storage_bucket=row.storage_bucket,
        object_identity=identity,
        **version_fields,
    )


def initiate_file_upload(
    credential: CredentialContext,
    name: str,
    filename: str,
    file_size: int,
    *,
    scope: ResourceScope | None,
    replaces: int | None = None,
) -> UploadInitiation:
    """Use the existing signed staging capability for opaque input bytes."""
    from ._scoped_uploads import initiate_scoped_upload

    return initiate_scoped_upload(
        credential, scope, name, filename, file_size, "", options=UploadOptions("file", replaces)
    )


def complete_file_upload(credential: CredentialContext, token: str) -> NamedFileAsset:
    """Complete only a live file-purpose admission through the common copy flow."""
    from ._scoped_uploads import complete_scoped_upload

    return cast(NamedFileAsset, complete_scoped_upload(credential, token, asset_kind="file"))


def cancel_file_upload(credential: CredentialContext, token: str) -> None:
    """Cancel only this file admission; retained cleanup remains authoritative."""
    from ._scoped_uploads import cancel_scoped_upload

    cancel_scoped_upload(credential, token, asset_kind="file")


def list_file_assets(credential: CredentialContext, *, scope: ResourceScope | None) -> list[dict[str, Any]]:
    """Return active metadata only after authorizing the selected content parent."""
    if scope is None:
        raise CMSError(_UNAVAILABLE)
    current = require_content_scope(credential, scope, "read_content")
    rows = NamedFileAsset.objects.filter(**content_scope_fields(scope))
    projection = [
        {
            "id": row.pk,
            "uuid": row.asset_uuid,
            "name": row.name,
            "original_filename": row.original_filename,
            "file_size_bytes": row.file_size_bytes,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    require_content_scope(current, scope, "read_content")
    return projection


def delete_file_asset(credential: CredentialContext, identifier: int) -> None:
    """Retire an exact version; existing range uses keep their original bytes."""
    snapshot = file_asset_for_action(credential, identifier, "manage_content")
    scope = content_scope(snapshot)
    current = require_content_scope(credential, scope, "manage_content")
    upload = AgentUpload.objects.filter(
        file_asset_id=snapshot.pk, install_key=snapshot.s3_key, state="completed"
    ).first()
    if upload is None:
        raise CMSError(_UNAVAILABLE)
    with transaction.atomic():
        AgentUploadBudget.objects.select_for_update().get(pk=upload.scope_digest)
        row = (
            NamedFileAsset.objects.select_for_update()
            .filter(
                pk=snapshot.pk,
                owner_principal_uuid=snapshot.owner_principal_uuid,
                scope_generation=snapshot.scope_generation,
                s3_key=snapshot.s3_key,
                **content_scope_fields(scope),
            )
            .first()
        )
        if row is None:
            raise CMSError(_UNAVAILABLE)
        fence_content_scope(current, scope)
        row.deleted_at = timezone.now()
        row.save(update_fields=["deleted_at"])
        AgentUpload.objects.filter(pk=upload.pk).update(cleanup_pending=True)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.FILE_ASSET,
                entity_id=row.pk,
                action=AuditAction.DELETE,
                **principal_actor_fields(current.principal),
                new_state={"upload_id": str(upload.pk)},
            ),
            strict=True,
        )
