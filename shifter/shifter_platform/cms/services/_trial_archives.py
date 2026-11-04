"""Tenant-authorized central custody with reserve, verify, and atomic receipt."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cms.models import TrialArchiveDestination, TrialArchiveReceipt, TrialArchiveTransfer
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.cloud import get_object_storage
from shared.cloud.exceptions import CloudStorageError
from shared.cloud.types import ObjectStorage
from shared.credentials import CredentialContext
from shared.exceptions import CMSError
from shared.identity_scope import ResourceScope
from shared.raes.trial_archive import (
    CHUNK_BYTES,
    MAX_ARCHIVE_BYTES,
    TrialArchiveError,
    TrialArchiveIdentity,
    VerifiedTrialArchive,
    safe_archive_path,
    validate_trial_archive,
)
from workspaces.services import OrganizationAuthorizationError

from ._content_authority import fence_content_scope, require_content_scope
from ._tenant_pack_authority import TenantPackAdmission
from ._tenant_pack_authority import admit_tenant_pack as _admit_tenant_pack
from ._tenant_pack_authority import fence_tenant_pack as _fence_tenant_pack


def _admit(
    credential: CredentialContext, organization_uuid: UUID, operation: str = "manage_content"
) -> TenantPackAdmission:
    """Resolve current tenant content authority with a body-free refusal."""
    try:
        return _admit_tenant_pack(credential, organization_uuid, operation)
    except OrganizationAuthorizationError:
        raise CMSError("Archive access denied") from None


def _fence(admission: TenantPackAdmission) -> None:
    """Hold tenant ancestry and local credential state through a custody write."""
    try:
        _fence_tenant_pack(admission)
    except OrganizationAuthorizationError:
        raise CMSError("Archive access denied") from None


@dataclass(frozen=True, slots=True)
class TrialArchiveCollection:
    """Body-free receipt or incomplete-transfer projection."""

    id: UUID
    transfer_id: UUID
    collection_status: str
    worker_copy_disposable: bool
    expected: dict[str, str]
    archive_digest: str
    run_status: str = ""
    outcome_status: str = ""
    evidence_complete: bool = False
    gap_count: int = 0
    failure_code: str = ""
    expires_at: datetime | None = None
    plan_metadata: dict[str, object] | None = None


def _audit(
    credential: CredentialContext, organization_uuid: UUID, reference: UUID, action: AuditAction, disposition: str
) -> None:
    """Write an opaque custody event through the existing strict audit boundary."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.EXPERIMENT,
            entity_id=0,
            entity_ref=str(reference),
            action=action,
            **principal_actor_fields(credential.principal),
            new_state={"organization_uuid": str(organization_uuid), "disposition": disposition},
        ),
        strict=True,
    )


def configure_trial_archive_destination(
    credential: CredentialContext, organization_uuid: UUID, *, bucket: str, prefix: str, retention_days: int | None
) -> None:
    """Explicitly bind an approved existing destination; never create storage."""
    operator = require_content_scope(credential, ResourceScope("installation"), "manage_content")
    admission = _admit(operator, organization_uuid)
    if not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", bucket):
        raise CMSError("Invalid archive destination")
    try:
        safe_archive_path(prefix)
    except TrialArchiveError:
        raise CMSError("Invalid archive destination") from None
    if len(prefix) > 256 or (
        retention_days is not None and (type(retention_days) is not int or not 1 <= retention_days <= 36500)
    ):
        raise CMSError("Explicit archive retention must be indefinite or 1 to 36500 days")
    with transaction.atomic():
        fence_content_scope(operator, ResourceScope("installation"))
        _fence(admission)
        TrialArchiveDestination.objects.update_or_create(
            organization_uuid=organization_uuid,
            defaults={"bucket": bucket, "prefix": prefix, "retention_days": retention_days},
        )
        _audit(operator, organization_uuid, organization_uuid, AuditAction.UPDATE, "archive-destination-configured")


def _identity_digest(expected: TrialArchiveIdentity) -> str:
    # Digests bind admission, but changing them cannot evade a committed
    # scientific identity's conflict check. Run versions are scientific identity.
    """Bind scientific identity independently of admission digest changes."""
    identity = {key: value for key, value in asdict(expected).items() if key not in {"plan_digest", "entry_digest"}}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reserve(admission: TenantPackAdmission, expected: TrialArchiveIdentity) -> TrialArchiveTransfer:
    """Persist a unique owned object key and pinned policy before storage I/O."""
    with transaction.atomic(durable=True):
        _fence(admission)
        destination = TrialArchiveDestination.objects.filter(organization_uuid=admission.organization_uuid).first()
        if destination is None:
            raise CMSError("Approved archive destination and retention are not configured")
        transfer_id = uuid4()
        row = TrialArchiveTransfer.objects.create(
            id=transfer_id,
            organization_uuid=admission.organization_uuid,
            expected=asdict(expected),
            identity_digest=_identity_digest(expected),
            bucket=destination.bucket,
            object_key=f"{destination.prefix}/trial-archives/{transfer_id}.tar.gz",
            retention_days=destination.retention_days,
            expires_at=timezone.now() + timedelta(days=destination.retention_days)
            if destination.retention_days
            else None,
        )
        _audit(
            admission.credential, admission.organization_uuid, row.pk, AuditAction.CREATE, "archive-transfer-pending"
        )
        return row


def _snapshot(source: BinaryIO, path: Path) -> tuple[int, str]:
    """Copy and hash one bounded input stream to private staging disk."""
    digest, size = hashlib.sha256(), 0
    path.touch(mode=0o600, exist_ok=False)
    with path.open("wb") as target:
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise TrialArchiveError("Archive exceeds its compressed size bound")
            target.write(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _verify_destination(storage: ObjectStorage, transfer: TrialArchiveTransfer, target: Path) -> dict[str, object]:
    """Verify the pinned object version, byte count, and complete SHA-256."""
    identity = storage.head_object(transfer.bucket, transfer.object_key)
    if transfer.object_identity and identity != transfer.object_identity:
        raise CMSError("Archive destination version changed")
    if identity.get("content_length") != transfer.archive_bytes or not (
        identity.get("etag") or identity.get("generation")
    ):
        raise CMSError("Archive destination verification failed")
    storage.download_object(
        transfer.bucket,
        transfer.object_key,
        str(target),
        max_bytes=max(1, transfer.archive_bytes),
        expected_identity=identity,
    )
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if target.stat().st_size != transfer.archive_bytes or digest != transfer.archive_digest:
        raise CMSError("Archive destination verification failed")
    return identity


def _view(receipt: TrialArchiveReceipt) -> TrialArchiveCollection:
    """Project receipt disposition without exposing retained scientific content."""
    expired = receipt.state == "expired" or (receipt.expires_at is not None and receipt.expires_at <= timezone.now())
    return TrialArchiveCollection(
        id=receipt.id,
        transfer_id=receipt.transfer_id,
        collection_status="expired" if expired else "committed",
        worker_copy_disposable=not expired,
        expected=receipt.transfer.expected,
        archive_digest=receipt.archive_digest,
        run_status=receipt.run_status,
        outcome_status=receipt.outcome_status,
        evidence_complete=receipt.evidence_complete,
        gap_count=receipt.gap_count,
        expires_at=receipt.expires_at,
        plan_metadata=receipt.transfer.plan_metadata,
    )


def _prior(transfer: TrialArchiveTransfer) -> TrialArchiveReceipt | None:
    """Resolve an existing identity and reject changed committed bytes."""
    prior = (
        TrialArchiveReceipt.objects.select_related("transfer")
        .filter(organization_uuid=transfer.organization_uuid, identity_digest=transfer.identity_digest)
        .first()
    )
    if prior is not None and prior.archive_digest != transfer.archive_digest:
        raise CMSError("Archive identity conflict: committed bytes differ")
    return prior


def _publish(
    admission: TenantPackAdmission,
    transfer: TrialArchiveTransfer,
    facts: VerifiedTrialArchive,
    identity: dict[str, object],
) -> TrialArchiveCollection:
    # The unique constraint handles concurrent finalizers. Each contender owns
    # a distinct object; get_or_create never overwrites the winning receipt.
    """Atomically commit verified custody or converge with an identical receipt."""
    with transaction.atomic(durable=True):
        _fence(admission)
        current = TrialArchiveTransfer.objects.select_for_update().get(pk=transfer.pk)
        if current.state != "verified" or not current.settled or current.object_identity != identity:
            raise CMSError("Archive transfer cannot publish")
        receipt, created = TrialArchiveReceipt.objects.get_or_create(
            organization_uuid=transfer.organization_uuid,
            identity_digest=transfer.identity_digest,
            defaults={
                "transfer": current,
                "archive_digest": current.archive_digest,
                **{key: value for key, value in asdict(facts).items() if key != "plan_metadata"},
                "expires_at": timezone.now() + timedelta(days=current.retention_days)
                if current.retention_days
                else None,
            },
        )
        if receipt.archive_digest != current.archive_digest:
            raise CMSError("Archive identity conflict: committed bytes differ")
        current.state = "committed" if created else "duplicate"
        if created:
            current.expires_at = receipt.expires_at
        current.save(update_fields=["state", "expires_at", "updated_at"])
        _audit(admission.credential, transfer.organization_uuid, receipt.pk, AuditAction.ARCHIVE, current.state)
        return _view(receipt)


def intake_trial_archive(
    credential: CredentialContext, organization_uuid: UUID, expected: TrialArchiveIdentity, source: BinaryIO
) -> TrialArchiveCollection:
    """Return a receipt only after all original bytes verify at the destination."""
    if not isinstance(expected, TrialArchiveIdentity):
        raise CMSError("Expected archive identity is required")
    admission = _admit(credential, organization_uuid)
    transfer = _reserve(admission, expected)
    upload_started = False
    try:
        storage = get_object_storage()
        with tempfile.TemporaryDirectory(prefix="trial-archive-") as temporary:
            source_path, downloaded = Path(temporary) / "source", Path(temporary) / "verified"
            transfer.archive_bytes, transfer.archive_digest = _snapshot(source, source_path)
            facts = validate_trial_archive(source_path, expected)
            transfer.plan_metadata = facts.plan_metadata
            transfer.save(update_fields=["archive_bytes", "archive_digest", "plan_metadata", "updated_at"])
            prior = _prior(transfer)
            if prior is not None:
                if _view(prior).worker_copy_disposable:
                    _verify_destination(storage, prior.transfer, downloaded)
                _admit(credential, organization_uuid)
                TrialArchiveTransfer.objects.filter(pk=transfer.pk).update(state="duplicate", settled=True)
                return _view(prior)
            # Recheck live authority before the first external storage effect.
            _admit(credential, organization_uuid)
            upload_started = True
            with source_path.open("rb") as body:
                storage.upload_file(body, transfer.bucket, transfer.object_key, "application/gzip")
            transfer.settled = True
            transfer.save(update_fields=["settled", "updated_at"])
            identity = _verify_destination(storage, transfer, downloaded)
            if not TrialArchiveTransfer.objects.filter(pk=transfer.pk, state="pending", settled=True).update(
                state="verified", object_identity=identity
            ):
                raise CMSError("Archive transfer lost publication authority")
            fresh = _admit(credential, organization_uuid)
            return _publish(fresh, transfer, facts, identity)
    except (TrialArchiveError, CMSError, CloudStorageError, OSError) as exc:
        invalid = isinstance(exc, TrialArchiveError)
        TrialArchiveTransfer.objects.filter(pk=transfer.pk).update(
            failure_code="invalid-archive" if invalid else "transfer-unverified",
            settled=transfer.settled or not upload_started,
        )
        if isinstance(exc, CMSError):
            raise
        message = (
            "Archive validation failed; keep the worker evidence copy"
            if invalid
            else "Archive transfer unverified; keep the worker copy and retry"
        )
        raise CMSError(message) from None


def list_trial_archives(
    credential: CredentialContext,
    organization_uuid: UUID,
    *,
    offset: int = 0,
    limit: int = 100,
    experiment_id: str | None = None,
) -> list[TrialArchiveCollection]:
    """List tenant-filtered receipts and incomplete custody without bucket scans."""
    _admit(credential, organization_uuid, "read_content")
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
        raise CMSError("Invalid archive page")
    rows = TrialArchiveTransfer.objects.filter(organization_uuid=organization_uuid).exclude(
        expected__has_key="artifact_kind"
    )
    if experiment_id is not None:
        if not isinstance(experiment_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", experiment_id):
            raise CMSError("Invalid experiment archive selector")
        rows = rows.filter(expected__experiment_id=experiment_id)
    rows = rows.select_related("trialarchivereceipt").order_by("created_at", "id")[offset : offset + limit]
    return [_transfer_view(row) for row in rows]


def publish_experiment_export(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID, files: dict[str, bytes]
) -> dict[str, object]:
    """Publish derived indexes only within the tenant's configured approved destination."""
    _validate_export_files(batch_id, files)
    admission = _admit(credential, organization_uuid)
    destination = TrialArchiveDestination.objects.filter(organization_uuid=organization_uuid).first()
    if destination is None:
        raise CMSError("Approved export destination is not configured")
    digests = {role: hashlib.sha256(body).hexdigest() for role, body in files.items()}
    digest = hashlib.sha256(json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="experiment-export-") as temporary:
        prior = _prior_export(admission, destination, batch_id, digest)
        if prior and _verify_prior_export(credential, destination, prior, Path(temporary)):
            return _export_references(prior, batch_id, digest)
        rows = _reserve_export(admission, destination, batch_id, digest, files)
        try:
            for row in rows:
                _export_authority(credential, destination)
                storage = get_object_storage()
                role = row.expected["file_role"]
                storage.upload_file(
                    io.BytesIO(files[role]),
                    row.bucket,
                    row.object_key,
                    "text/csv" if role == "csv" else "application/json",
                )
                row.settled = True
                row.save(update_fields=["settled", "updated_at"])
                row.object_identity = _verify_destination(storage, row, Path(temporary) / str(row.id))
                row.state = "verified"
                row.save(update_fields=["object_identity", "state", "updated_at"])
            fresh = _export_authority(credential, destination)
            with transaction.atomic():
                _fence(fresh)
                for row in rows:
                    current = TrialArchiveTransfer.objects.select_for_update().get(pk=row.pk)
                    if current.state != "verified" or (current.expires_at and current.expires_at <= timezone.now()):
                        raise CMSError("Experiment export publication expired")
                    current.state = "committed"
                    current.save(update_fields=["state", "updated_at"])
                _audit(credential, organization_uuid, rows[-1].id, AuditAction.ARCHIVE, "experiment-export-committed")
            return _export_references(rows, batch_id, digest)
        except (CloudStorageError, OSError):
            raise CMSError("Experiment export publication unverified; retry") from None


def _verify_prior_export(
    credential: CredentialContext,
    destination: TrialArchiveDestination,
    rows: list[TrialArchiveTransfer],
    temporary: Path,
) -> bool:
    """Reuse intact files or rebuild at fresh keys, preserving current read authority."""
    for row in rows:
        _export_authority(credential, destination)
        try:
            _verify_destination(get_object_storage(), row, temporary / str(row.id))
        except (CMSError, CloudStorageError, OSError):
            return False
    fresh = _export_authority(credential, destination)
    with transaction.atomic():
        _fence(fresh)
        current = list(TrialArchiveTransfer.objects.select_for_update().filter(pk__in=[row.pk for row in rows]))
        if len(current) != 3 or any(
            row.state != "committed" or (row.expires_at is not None and row.expires_at <= timezone.now())
            for row in current
        ):
            return False
        _audit(credential, destination.organization_uuid, rows[0].id, AuditAction.DOWNLOAD, "experiment-export-reused")
    return True


def _validate_export_files(batch_id: UUID, files: dict[str, bytes]) -> None:
    """Require the complete fixed output set within its independent custody bound."""
    if not isinstance(batch_id, UUID) or set(files) != {"manifest", "json", "csv"}:
        raise CMSError("Invalid experiment export")
    if (
        any(not isinstance(body, bytes) or not body for body in files.values())
        or sum(map(len, files.values())) > 128 * 1024**2
    ):
        raise CMSError("Experiment export exceeds its supported size limit")


_EXPORT_NAMES = {"json": "index.json", "csv": "index.csv", "manifest": "manifest.json"}


def _export_authority(credential: CredentialContext, destination: TrialArchiveDestination) -> TenantPackAdmission:
    """Recheck current content authority and the exact approved destination policy."""
    _admit(credential, destination.organization_uuid, "read_content")
    admission = _admit(credential, destination.organization_uuid)
    current = TrialArchiveDestination.objects.filter(pk=destination.pk).first()
    if current is None or any(
        getattr(current, key) != getattr(destination, key)
        for key in ("bucket", "prefix", "retention_days", "updated_at")
    ):
        raise CMSError("Approved export destination changed; retry")
    return admission


def _reserve_export(
    admission: TenantPackAdmission,
    destination: TrialArchiveDestination,
    batch_id: UUID,
    digest: str,
    files: dict[str, bytes],
) -> list[TrialArchiveTransfer]:
    """Journal independently owned derived objects using the existing retention fence."""
    publication_id = uuid4()
    expires = timezone.now() + timedelta(days=destination.retention_days) if destination.retention_days else None
    rows = []
    _export_authority(admission.credential, destination)
    with transaction.atomic(durable=True):
        _fence(admission)
        current = TrialArchiveDestination.objects.select_for_update().filter(pk=destination.pk).first()
        if current is None or any(
            getattr(current, key) != getattr(destination, key)
            for key in ("bucket", "prefix", "retention_days", "updated_at")
        ):
            raise CMSError("Approved export destination changed; retry")
        for role, name in _EXPORT_NAMES.items():
            row = TrialArchiveTransfer.objects.create(
                organization_uuid=admission.organization_uuid,
                expected={
                    "artifact_kind": "experiment-export",
                    "batch_id": str(batch_id),
                    "export_digest": digest,
                    "publication_id": str(publication_id),
                    "file_role": role,
                    "destination_prefix": destination.prefix,
                },
                identity_digest=hashlib.sha256(f"{publication_id}:{role}".encode()).hexdigest(),
                bucket=destination.bucket,
                object_key=f"{destination.prefix}/experiment-exports/{batch_id}/{digest}/{publication_id}/{name}",
                retention_days=destination.retention_days,
                expires_at=expires,
                archive_bytes=len(files[role]),
                archive_digest=hashlib.sha256(files[role]).hexdigest(),
            )
            rows.append(row)
        _audit(
            admission.credential,
            admission.organization_uuid,
            publication_id,
            AuditAction.CREATE,
            "experiment-export-pending",
        )
    return rows


def _prior_export(
    admission: TenantPackAdmission, destination: TrialArchiveDestination, batch_id: UUID, digest: str
) -> list[TrialArchiveTransfer]:
    """Reuse only a complete publication under the same unexpired destination policy."""
    rows = (
        TrialArchiveTransfer.objects.filter(
            organization_uuid=admission.organization_uuid,
            bucket=destination.bucket,
            retention_days=destination.retention_days,
            expected__artifact_kind="experiment-export",
            expected__batch_id=str(batch_id),
            expected__export_digest=digest,
            expected__destination_prefix=destination.prefix,
            expected__file_role="manifest",
            state="committed",
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("-created_at", "id")
    )
    manifest = rows.first()
    if manifest is None:
        return []
    group = list(
        TrialArchiveTransfer.objects.filter(
            organization_uuid=admission.organization_uuid,
            expected__publication_id=manifest.expected["publication_id"],
            state="committed",
            settled=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("id")[:4]
    )
    return group if len(group) == 3 and {row.expected["file_role"] for row in group} == set(_EXPORT_NAMES) else []


def _export_references(rows: list[TrialArchiveTransfer], batch_id: UUID, digest: str) -> dict[str, object]:
    """Return authorized opaque storage references without scientific bodies."""
    return {
        "batch_id": str(batch_id),
        "export_digest": digest,
        "bucket": rows[0].bucket,
        "files": {row.expected["file_role"]: row.object_key for row in rows},
    }


def _transfer_view(row: TrialArchiveTransfer) -> TrialArchiveCollection:
    """Project a receipt or a journal row without a nested disposition expression."""
    receipt = getattr(row, "trialarchivereceipt", None)
    if receipt:
        return _view(receipt)
    return TrialArchiveCollection(
        id=row.id,
        transfer_id=row.id,
        collection_status=row.state,
        worker_copy_disposable=False,
        expected=row.expected,
        archive_digest=row.archive_digest,
        gap_count=1 if row.failure_code else 0,
        failure_code=row.failure_code,
        expires_at=row.expires_at,
        plan_metadata=row.plan_metadata,
    )


def retrieve_trial_archive(
    credential: CredentialContext, organization_uuid: UUID, receipt_id: UUID, target: Path
) -> None:
    """Download the exact authorized stored bytes; never return a signed URL."""
    admission = _admit(credential, organization_uuid, "read_content")
    receipt = (
        TrialArchiveReceipt.objects.select_related("transfer")
        .filter(pk=receipt_id, organization_uuid=organization_uuid)
        .first()
    )
    if receipt is None or not _view(receipt).worker_copy_disposable:
        raise CMSError("Archive unavailable")
    try:
        with tempfile.TemporaryDirectory(prefix="trial-retrieve-", dir=target.parent) as temporary:
            staged = Path(temporary) / "archive"
            _verify_destination(get_object_storage(), receipt.transfer, staged)
            fresh = _admit(credential, organization_uuid, "read_content")
            with transaction.atomic():
                _fence(fresh)
                current = TrialArchiveReceipt.objects.select_for_update().get(pk=receipt.id)
                if not _view(current).worker_copy_disposable:
                    raise CMSError("Archive unavailable")
                # Link with exclusive destination creation: no arbitrary local
                # path replacement, and no partial output on a failed download.
                _audit(admission.credential, organization_uuid, receipt.id, AuditAction.DOWNLOAD, "archive-retrieved")
            staged.chmod(0o600)
            target.hardlink_to(staged)
    except (OSError, CloudStorageError):
        raise CMSError("Archive retrieval unavailable") from None


def purge_trial_archives(credential: CredentialContext, organization_uuid: UUID, *, limit: int = 100) -> int:
    """Expire access first, then delete only settled, exactly owned objects."""
    admission = _admit(credential, organization_uuid)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise CMSError("Invalid archive purge bound")
    purged = 0
    now = timezone.now()
    transfers = (
        TrialArchiveTransfer.objects.filter(organization_uuid=organization_uuid, settled=True)
        .exclude(state="purged")
        .filter(Q(trialarchivereceipt__expires_at__lte=now) | Q(trialarchivereceipt__isnull=True, expires_at__lte=now))
        .order_by("id")[:limit]
    )
    storage = get_object_storage()
    for transfer in transfers:
        admission = _admit(credential, organization_uuid)
        if not _claim_retention(admission, transfer.id):
            continue
        try:
            storage.delete_object(transfer.bucket, transfer.object_key)
            if storage.object_exists(transfer.bucket, transfer.object_key):
                continue
        except CloudStorageError:
            continue
        with transaction.atomic():
            _fence(admission)
            TrialArchiveTransfer.objects.filter(pk=transfer.pk).update(state="purged")
            _audit(admission.credential, organization_uuid, transfer.id, AuditAction.DELETE, "archive-expired")
        purged += 1
    return purged


def _claim_retention(admission: TenantPackAdmission, transfer_id: UUID) -> bool:
    """Fence publication before any deletion, including abandoned verified uploads."""
    with transaction.atomic():
        _fence(admission)
        transfer = TrialArchiveTransfer.objects.select_for_update().get(pk=transfer_id)
        if not transfer.settled or transfer.state == "purged":
            return False
        receipt = TrialArchiveReceipt.objects.select_for_update().filter(transfer_id=transfer_id).first()
        deadline = receipt.expires_at if receipt else transfer.expires_at
        if deadline is None or deadline > timezone.now():
            return False
        if receipt:
            receipt.state = "expired"
            receipt.save(update_fields=["state"])
        transfer.state = "purging"
        transfer.save(update_fields=["state", "updated_at"])
        _audit(admission.credential, admission.organization_uuid, transfer_id, AuditAction.ARCHIVE, "archive-expired")
        return True
