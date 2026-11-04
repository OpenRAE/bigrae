"""Derived export publication through existing tenant archive custody primitives."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cms.models import TrialArchiveDestination, TrialArchiveTransfer
from shared.audit import AuditAction
from shared.cloud.exceptions import CloudStorageError
from shared.credentials import CredentialContext
from shared.exceptions import CMSError

from . import _trial_archives as custody
from ._tenant_pack_authority import TenantPackAdmission


def publish_experiment_export(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID, files: dict[str, bytes]
) -> dict[str, object]:
    """Publish derived indexes only within the tenant's configured approved destination."""
    _validate_export_files(batch_id, files)
    admission = custody._admit(credential, organization_uuid)
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
                storage = custody.get_object_storage()
                role = row.expected["file_role"]
                storage.upload_file(
                    io.BytesIO(files[role]),
                    row.bucket,
                    row.object_key,
                    "text/csv" if role == "csv" else "application/json",
                )
                row.settled = True
                row.save(update_fields=["settled", "updated_at"])
                row.object_identity = custody._verify_destination(storage, row, Path(temporary) / str(row.id))
                row.state = "verified"
                row.save(update_fields=["object_identity", "state", "updated_at"])
            _commit_export(credential, destination, rows)
            return _export_references(rows, batch_id, digest)
        except (CloudStorageError, OSError):
            raise CMSError("Experiment export publication unverified; retry") from None


def _commit_export(
    credential: CredentialContext, destination: TrialArchiveDestination, rows: list[TrialArchiveTransfer]
) -> None:
    """Fence current authority and atomically commit only verified, unexpired files."""
    fresh = _export_authority(credential, destination)
    with transaction.atomic():
        custody._fence(fresh)
        for row in rows:
            current = TrialArchiveTransfer.objects.select_for_update().get(pk=row.pk)
            if current.state != "verified" or (current.expires_at and current.expires_at <= timezone.now()):
                raise CMSError("Experiment export publication expired")
            current.state = "committed"
            current.save(update_fields=["state", "updated_at"])
        custody._audit(
            credential, destination.organization_uuid, rows[-1].id, AuditAction.ARCHIVE, "experiment-export-committed"
        )


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
            custody._verify_destination(custody.get_object_storage(), row, temporary / str(row.id))
        except (CMSError, CloudStorageError, OSError):
            return False
    fresh = _export_authority(credential, destination)
    with transaction.atomic():
        custody._fence(fresh)
        current = list(TrialArchiveTransfer.objects.select_for_update().filter(pk__in=[row.pk for row in rows]))
        if len(current) != 3 or any(
            row.state != "committed" or (row.expires_at is not None and row.expires_at <= timezone.now())
            for row in current
        ):
            return False
        custody._audit(
            credential, destination.organization_uuid, rows[0].id, AuditAction.DOWNLOAD, "experiment-export-reused"
        )
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
    custody._admit(credential, destination.organization_uuid, "read_content")
    admission = custody._admit(credential, destination.organization_uuid)
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
        custody._fence(admission)
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
        custody._audit(
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
