"""Native tenant admission and short, fenced operational transactions."""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import batched
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from cms.models import (
    ExperimentBatch,
    ExperimentEntry,
    ExperimentSnapshot,
    RaesPackageSource,
    TrialArchiveDestination,
    TrialArchiveReceipt,
)
from cms.scenarios.pack_validation import PackDigestError, verify_pack_digest
from shared.cloud import get_object_storage
from shared.cloud.exceptions import CloudStorageError
from shared.credentials import CredentialContext
from shared.disposable_workers import WorkerProfileError
from shared.exceptions import CMSError, ValidationError
from shared.identity_scope import ResourceScope
from shared.raes.experiment_admission import (
    ExperimentInputError,
    InstallationLookups,
    compile_pack_experiment,
    encode_retained,
    experiment_archive_identity,
    read_snapshots,
    validate_experiment_cleanup,
    validate_retained,
)
from shared.raes.experiment_pack_snapshot import stage_local_experiment_pack
from shared.raes.object_source import stage_object_pack
from shared.raes.package_loader import RaesPackageError, resolve_pack_root
from shared.raes.participant_owner_replay import OwnerValidation

from ._content_authority import content_scope, fence_content_scope, require_content_scope
from ._experiment_authority import _UNAVAILABLE, _audit, _authorize, _fence
from ._experiment_batch_records import ExperimentClaim, RetainedExperimentBatch
from ._tenant_pack_authority import TenantPackAdmission


def _project(row: ExperimentBatch) -> RetainedExperimentBatch:
    """Verify retained integrity before returning a fresh scientific projection."""
    if hashlib.sha256(row.retained_json.encode()).hexdigest() != row.retained_digest:
        raise CMSError(_UNAVAILABLE)
    try:
        payload = validate_retained(row.retained_json)
        if (
            payload["plan"]["plan_id"] != row.plan_id
            or payload["resource_limits"]["requested_concurrency"] != row.concurrency
            or payload["organization_uuid"] != str(row.organization_uuid)
        ):
            raise ValueError("Retained batch identity mismatch")
    except (ValueError, KeyError, TypeError, ExperimentInputError):
        raise CMSError(_UNAVAILABLE) from None
    return RetainedExperimentBatch(row.id, payload)


def load_experiment_batch(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch_id: UUID,
) -> RetainedExperimentBatch:
    """Reload exact retained inputs, never a current pack or newly compiled plan."""
    admission = _authorize(credential, organization_uuid, "read_content")
    return _load(admission, batch_id)


def list_experiment_entries(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID
) -> list[dict[str, Any]]:
    """Read the batch's operational assignments without manufacturing scientific facts."""
    admission = _authorize(credential, organization_uuid, "read_content")
    if not ExperimentBatch.objects.filter(pk=batch_id, organization_uuid=admission.organization_uuid).exists():
        raise CMSError(_UNAVAILABLE)
    return [
        {
            "plan_entry_id": row.plan_entry_id,
            "run_id": row.run_id,
            "execution_attempt_id": str(row.token) if row.token else None,
            "state": row.state,
            "worker_ref": row.worker_ref or None,
            "collection_receipt_id": str(row.receipt_id) if row.receipt_id else None,
            "run_status": row.receipt.run_status if row.receipt else None,
            "data_complete": row.receipt.evidence_complete if row.receipt else None,
            "cleanup_recorded": bool(row.cleanup_receipt_json),
            "attempt": row.replacement_ordinal or 0,
            "replaces_attempt_id": str(row.replaces.token) if row.replaces else None,
        }
        for row in ExperimentEntry.objects.filter(batch_id=batch_id, organization_uuid=organization_uuid)
        .select_related("receipt", "replaces")
        .order_by("plan_entry_id", F("replacement_ordinal").asc(nulls_first=True))
    ]


def _load(admission: TenantPackAdmission, batch_id: UUID) -> RetainedExperimentBatch:
    """Load only a batch owned by the authorized organization."""
    row = ExperimentBatch.objects.filter(pk=batch_id, organization_uuid=admission.organization_uuid).first()
    if row is None:
        raise CMSError(_UNAVAILABLE)
    return _project(row)


@contextmanager
def _pack_snapshot(source: RaesPackageSource) -> Iterator[Path]:
    """Stage installed bytes through the existing local or object-pack boundary."""
    if source.source_kind == "repo":
        root = resolve_pack_root(source.package_ref, package_root=Path(settings.RAES_PACKAGE_ROOT))
        with stage_local_experiment_pack(
            root, max_bytes=settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES, max_entries=settings.RAES_PACKAGE_MAX_ENTRIES
        ) as snapshot:
            yield snapshot
    elif source.source_kind == "object":
        prefix = settings.RAES_PACKAGE_PREFIX.strip("/")
        key = f"{prefix}/{source.package_ref.lstrip('/')}" if prefix else source.package_ref.lstrip("/")
        with stage_object_pack(
            storage=get_object_storage(),
            bucket=settings.RAES_PACKAGE_BUCKET,
            key=key,
            max_archive_bytes=settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES,
            max_uncompressed_bytes=settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES,
            max_entries=settings.RAES_PACKAGE_MAX_ENTRIES,
            expected_pack_name=source.package_identity,
        ) as snapshot:
            yield snapshot
    else:
        raise CMSError(_UNAVAILABLE)


def _destination(organization_uuid: UUID, *, locked: bool = False) -> dict[str, Any]:
    """Require an approved archive destination, optionally locking its policy."""
    rows = TrialArchiveDestination.objects.all()
    if locked:
        rows = rows.select_for_update()
    row = rows.filter(organization_uuid=organization_uuid).values("bucket", "prefix", "retention_days").first()
    if row is None:
        raise CMSError("Approved experiment archive destination required")
    return dict(row)


def _source_unchanged(
    current: RaesPackageSource | None, source: RaesPackageSource, admission: TenantPackAdmission
) -> bool:
    """Compare all source custody fields after acquiring the database fence."""
    if current is None or content_scope(current) != admission.scope:
        return False
    fields = (
        "scope_generation",
        "package_digest",
        "package_ref",
        "package_version",
        "source_kind",
        "owner_principal_uuid",
    )
    return all(getattr(current, name) == getattr(source, name) for name in fields)


def _owner_validation(organization_uuid: UUID) -> OwnerValidation:
    """Run backend participant owners in the organization's installed adapter."""
    from engine.services import validate_participant_configurations

    return lambda owner, family_digest, requests: validate_participant_configurations(
        organization_uuid, owner=owner, family_digest=family_digest, requests=requests
    )


def _retain_snapshots(
    row: ExperimentBatch, payload: dict[str, Any], snapshots: BinaryIO, written: list[tuple[str, int]]
) -> None:
    """Verify each written snapshot and insert it in small groups, because one snapshot can be more than 1 MB."""
    try:
        for group in batched(read_snapshots(payload, snapshots, written), 16):
            ExperimentSnapshot.objects.bulk_create(
                ExperimentSnapshot(batch=row, plan_entry_id=key, snapshot_json=snapshot.decode())
                for key, snapshot in group
            )
    except ValueError:
        raise CMSError("Experiment admission refused; verify installed inputs, versions and limits") from None


def admit_experiment_batch(
    credential: CredentialContext,
    organization_uuid: UUID,
    *,
    scenario_id: str,
    experiment_id: str,
    authority: object,
    concurrency: int,
    experiment_version: str | None = None,
) -> RetainedExperimentBatch:
    """Approve apparatus and atomically retain a complete tenant-owned pack plan.

    Instantiated trial snapshots go to a temporary file, so memory does not grow with the number of trials.
    """
    with tempfile.TemporaryFile(prefix="experiment-snapshots-") as snapshots:
        operator = require_content_scope(credential, ResourceScope("installation"), "manage_content")
        admission = _authorize(operator, organization_uuid, "manage_content")
        source = RaesPackageSource.objects.filter(scenario_id=scenario_id, organization_uuid=organization_uuid).first()
        if source is None or content_scope(source) != admission.scope:
            raise CMSError(_UNAVAILABLE)
        destination = _destination(organization_uuid)
        from engine.services import published_worker_profile

        try:
            with _pack_snapshot(source) as root:
                if not verify_pack_digest(root, source.package_digest):
                    raise ValueError("Registered pack digest changed")
                payload, written = compile_pack_experiment(
                    root,
                    experiment_id=experiment_id,
                    authority=authority,
                    concurrency=concurrency,
                    experiment_version=experiment_version,
                    installation=InstallationLookups(_owner_validation(organization_uuid), published_worker_profile),
                    snapshots=snapshots,
                )
        except WorkerProfileError:
            raise CMSError("Experiment admission refused; publish the selected worker profile first") from None
        except (
            ValueError,
            OSError,
            RaesPackageError,
            PackDigestError,
            ValidationError,
            CloudStorageError,
            ExperimentInputError,
        ):
            raise CMSError("Experiment admission refused; verify installed inputs, versions and limits") from None
        payload.update(
            organization_uuid=str(organization_uuid),
            destination=destination,
            source={"package_digest": source.package_digest, "package_version": source.package_version},
        )
        payload["resource_limits"]["pack_staging"] = {
            "max_archive_bytes": settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES,
            "max_expanded_bytes": settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES,
            "max_entries": settings.RAES_PACKAGE_MAX_ENTRIES,
        }
        try:
            retained = encode_retained(payload)
        except (ValueError, TypeError):
            raise CMSError("Experiment retained inputs exceed supported limits") from None
        digest = hashlib.sha256(retained.encode()).hexdigest()
        operator = require_content_scope(operator, ResourceScope("installation"), "manage_content")
        admission = _authorize(operator, organization_uuid, "manage_content")
        with transaction.atomic():
            fence_content_scope(operator, ResourceScope("installation"))
            _fence(admission)
            current = RaesPackageSource.objects.select_for_update().filter(pk=source.pk).first()
            if (
                not _source_unchanged(current, source, admission)
                or _destination(organization_uuid, locked=True) != destination
            ):
                raise CMSError(_UNAVAILABLE)
            row, created = ExperimentBatch.objects.get_or_create(
                organization_uuid=organization_uuid,
                plan_id=payload["plan"]["plan_id"],
                defaults={"retained_json": retained, "retained_digest": digest, "concurrency": concurrency},
            )
            if row.retained_digest != digest:
                raise CMSError("Experiment admission conflicts with retained inputs")
            if created:
                ExperimentEntry.objects.bulk_create(
                    [
                        ExperimentEntry(
                            batch=row, organization_uuid=organization_uuid, plan_entry_id=key, run_id=entry["run_id"]
                        )
                        for key, entry in payload["plan"]["entries"].items()
                    ]
                )
                _retain_snapshots(row, payload, snapshots, written)
                _audit(admission, row.id, "experiment-admitted")
        return _project(row)


def _claim(row: ExperimentEntry) -> ExperimentClaim:
    """Project one already bound attempt without changing its identities."""
    if row.token is None:
        raise CMSError(_UNAVAILABLE)
    return ExperimentClaim(
        row.token,
        row.batch_id,
        row.plan_entry_id,
        row.run_id,
        row.state,
        row.worker_ref,
        row.receipt_id,
        bool(row.cleanup_receipt_json),
    )


def claim_experiment_entry(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch_id: UUID,
    plan_entry_id: str,
) -> ExperimentClaim | None:
    """Serialize aggregate capacity, then conditionally claim one preallocated entry."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    batch = _load(admission, batch_id)
    with transaction.atomic():
        _fence(admission)
        parent = (
            ExperimentBatch.objects.select_for_update()
            .only("id", "concurrency", "dispatch_stopped_at")
            .get(pk=batch_id)
        )
        if (
            ExperimentEntry.objects.filter(batch=parent, cleanup_receipt_json="").exclude(state="pending").count()
            >= parent.concurrency
        ):
            return None
        row = _planned_entry(batch, organization_uuid, plan_entry_id)
        token = uuid4()
        if not ExperimentEntry.objects.filter(pk=row.pk, state="pending", token__isnull=True).update(
            token=token,
            state="claimed",
            updated_at=timezone.now(),
        ):
            return None
        row.token, row.state = token, "claimed"
        _audit(admission, row.id, "experiment-entry-claimed")
        return _claim(row)


def recover_experiment_claim(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch_id: UUID,
    plan_entry_id: str,
) -> ExperimentClaim | None:
    """Recover the existing attempt for reconciliation, without authorizing redispatch."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    batch = _load(admission, batch_id)
    with transaction.atomic():
        _fence(admission)
        row = _planned_entry(batch, organization_uuid, plan_entry_id)
        return None if row.token is None else _claim(row)


def _planned_entry(batch: RetainedExperimentBatch, organization_uuid: UUID, plan_entry_id: str) -> ExperimentEntry:
    """Resolve the entry's latest attempt: the one that no fresh trial replaces."""
    row = ExperimentEntry.objects.filter(
        batch_id=batch.id,
        batch__organization_uuid=organization_uuid,
        organization_uuid=organization_uuid,
        plan_entry_id=plan_entry_id,
        replacements__isnull=True,
    ).first()
    expected = batch.inputs["plan"]["entries"].get(plan_entry_id)
    if row is None or expected is None or expected["run_id"] != row.run_id:
        raise CMSError(_UNAVAILABLE)
    return row


def _attempt(organization_uuid: UUID, token: UUID, *, locked: bool) -> ExperimentEntry:
    """Resolve the exact tenant-owned attempt and optionally lock its row."""
    if not isinstance(token, UUID):
        raise CMSError(_UNAVAILABLE)
    rows = ExperimentEntry.objects.all()
    if locked:
        rows = rows.select_for_update()
    row = rows.filter(
        organization_uuid=organization_uuid, batch__organization_uuid=organization_uuid, token=token
    ).first()
    if row is None:
        raise CMSError(_UNAVAILABLE)
    return row


def record_experiment_worker(
    credential: CredentialContext,
    organization_uuid: UUID,
    token: UUID,
    worker_ref: str,
) -> ExperimentClaim:
    """Bind an opaque worker identity once, preserving identical replay."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    if not isinstance(worker_ref, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9/._:-]{0,255}", worker_ref):
        raise CMSError(_UNAVAILABLE)
    with transaction.atomic():
        _fence(admission)
        row = _attempt(organization_uuid, token, locked=True)
        if row.worker_ref and row.worker_ref != worker_ref:
            raise CMSError("Experiment worker identity conflict")
        if not row.worker_ref:
            row.worker_ref = worker_ref
            row.save(update_fields=["worker_ref", "updated_at"])
            _audit(admission, row.id, "experiment-worker-recorded")
        return _claim(row)


def observe_experiment_attempt(
    credential: CredentialContext,
    organization_uuid: UUID,
    token: UUID,
    state: str | None = None,
) -> ExperimentClaim:
    """Read or monotonically record a fixed operational disposition, without scientific scoring."""
    if state is not None and (not isinstance(state, str) or state not in {"claimed", "running", "finished", "failed"}):
        raise CMSError(_UNAVAILABLE)
    admission = _authorize(credential, organization_uuid, "read_content" if state is None else "manage_content")
    if state is None:
        return _claim(_attempt(organization_uuid, token, locked=False))
    with transaction.atomic():
        _fence(admission)
        row = _attempt(organization_uuid, token, locked=True)
        transitions = {"claimed": {"running", "finished", "failed"}, "running": {"finished", "failed"}}
        if state != row.state and state not in transitions.get(row.state, set()):
            raise CMSError("Experiment observation conflict")
        if row.state != state:
            row.state = state
            row.save(update_fields=["state", "updated_at"])
            _audit(admission, row.id, "experiment-attempt-observed")
        return _claim(row)


def record_experiment_collection(
    credential: CredentialContext,
    organization_uuid: UUID,
    token: UUID,
    receipt_id: UUID,
    *,
    run_version: str = "1",
    scenario_sha256: str = "",
) -> None:
    """Join committed archive custody to this exact attempt, without asserting cleanup."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    attempt = _attempt(organization_uuid, token, locked=False)
    batch = _load(admission, attempt.batch_id)
    try:
        expected = experiment_archive_identity(
            batch.inputs,
            attempt.plan_entry_id,
            str(token),
            run_version,
            scenario_sha256=scenario_sha256,
        ).as_record()
    except (ValueError, ValidationError):
        raise CMSError("Experiment collection identity is invalid") from None
    with transaction.atomic():
        _fence(admission)
        row = _attempt(organization_uuid, token, locked=True)
        receipt = (
            TrialArchiveReceipt.objects.select_for_update()
            .filter(
                pk=receipt_id,
                organization_uuid=organization_uuid,
                state="committed",
            )
            .select_related("transfer")
            .first()
        )
        destination = batch.inputs["destination"]
        if receipt is None:
            raise CMSError("Experiment collection receipt mismatch")
        actual_transfer = (
            receipt.transfer.organization_uuid,
            receipt.transfer.state,
            receipt.transfer.expected,
            receipt.transfer.bucket,
            receipt.transfer.retention_days,
        )
        expected_transfer = (
            organization_uuid,
            "committed",
            expected,
            destination["bucket"],
            destination["retention_days"],
        )
        if (
            actual_transfer != expected_transfer
            or (receipt.expires_at is not None and receipt.expires_at <= timezone.now())
            or not receipt.transfer.object_key.startswith(destination["prefix"] + "/trial-archives/")
            or _destination(organization_uuid, locked=True) != destination
            or (row.receipt_id is not None and row.receipt_id != receipt.id)
        ):
            raise CMSError("Experiment collection receipt mismatch")
        if row.receipt_id is None:
            row.receipt = receipt
            row.save(update_fields=["receipt", "updated_at"])
            _audit(admission, row.id, "experiment-collection-recorded")


def record_experiment_cleanup(
    credential: CredentialContext,
    organization_uuid: UUID,
    token: UUID,
    receipt: object,
) -> None:
    """Record verified owner evidence; collection or lease expiry cannot release capacity."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    attempt = _attempt(organization_uuid, token, locked=False)
    batch = _load(admission, attempt.batch_id)
    try:
        encoded = validate_experiment_cleanup(batch.inputs, attempt.plan_entry_id, str(token), receipt)
    except (ValueError, ValidationError):
        raise CMSError("Experiment cleanup is invalid or unverified") from None
    with transaction.atomic():
        _fence(admission)
        ExperimentBatch.objects.select_for_update().only("id").get(pk=attempt.batch_id)
        row = _attempt(organization_uuid, token, locked=True)
        if row.state not in {"finished", "failed"} or (
            row.cleanup_receipt_json and row.cleanup_receipt_json != encoded
        ):
            raise CMSError("Experiment cleanup observation conflict")
        if not row.cleanup_receipt_json:
            row.cleanup_receipt_json = encoded
            row.save(update_fields=["cleanup_receipt_json", "updated_at"])
            _audit(admission, row.id, "experiment-cleanup-recorded")
