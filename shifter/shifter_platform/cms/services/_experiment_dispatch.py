"""Run a retained experiment batch: one disposable worker for each admitted trial.

Each step reuses its owning service. Batch claims bound the concurrency, Engine
admits worker capacity, holds preserve evidence, archive intake records custody,
and retirement verifies provider absence. The coordinator keeps no state outside
those services, so a restart continues from them. It never starts a second
trial for an entry and never redispatches automatically.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from cms.models import ExperimentEntry, RaesPackageSource
from cms.scenarios.pack_validation import verify_pack_digest
from shared.cloud import get_object_storage
from shared.exceptions import CMSError
from shared.raes.experiment_admission import (
    entry_attempt_timeout,
    experiment_archive_identity,
    worker_absence_cleanup_receipt,
)
from shared.worker_trial import MAX_ARCHIVE_BYTES, TRIAL_INPUT_PREFIX, StagedObject

from ._experiment_batches import (
    _authorize,
    _load,
    _pack_snapshot,
    claim_experiment_entry,
    observe_experiment_attempt,
    record_experiment_cleanup,
    record_experiment_collection,
    record_experiment_worker,
)
from ._trial_archives import intake_trial_archive

if TYPE_CHECKING:
    from shared.identity_scope import CredentialContext, ResourceScope

_WORKER_NAMESPACE = uuid5(NAMESPACE_URL, "bigrae:experiment-worker")
_HOLD_REASON = "evidence"
_RUN_OUTCOMES = {"completed": "succeeded", "failed": "failed", "aborted": "aborted"}


@dataclass(frozen=True)
class DispatchStep:
    """One entry's observed position; ``action`` names what this pass did."""

    plan_entry_id: str
    execution_attempt_id: str | None
    worker_id: str | None
    trial_state: str | None
    collected: bool
    cleanup_recorded: bool
    action: str


def worker_id_for(token: UUID) -> UUID:
    """Derive the attempt's worker identity, so a lost response finds the same worker."""
    return uuid5(_WORKER_NAMESPACE, str(token))


def _entries(organization_uuid: UUID, batch_id: UUID) -> list[ExperimentEntry]:
    return list(
        ExperimentEntry.objects.filter(batch_id=batch_id, organization_uuid=organization_uuid).order_by("plan_entry_id")
    )


def _create_worker(
    credential: CredentialContext, organization_uuid: UUID, scope: ResourceScope, row: ExperimentEntry
) -> UUID:
    """Create or replay the attempt's worker and bind it to the attempt."""
    from engine.services import create_disposable_worker

    worker_id = worker_id_for(row.token)
    create_disposable_worker(
        credential, scope=scope, worker_id=worker_id, experiment_id=row.batch_id, trial_id=row.token
    )
    record_experiment_worker(credential, organization_uuid, row.token, f"worker:{worker_id}")
    return worker_id


def start_experiment_dispatch(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID, *, scope: ResourceScope
) -> list[DispatchStep]:
    """Claim pending entries up to the batch limit, create their workers, then reconcile."""
    _authorize(credential, organization_uuid, "manage_content")
    for row in _entries(organization_uuid, batch_id):
        if row.state != "pending":
            continue
        claim = claim_experiment_entry(credential, organization_uuid, batch_id, row.plan_entry_id)
        if claim is None:
            break
        row.refresh_from_db()
        try:
            _create_worker(credential, organization_uuid, scope, row)
        except ValueError:
            # Worker capacity is exhausted; reconcile retries the same worker identity.
            break
    return reconcile_experiment_dispatch(credential, organization_uuid, batch_id, scope=scope)


def _stage_object(storage: Any, key: str, data: bytes) -> StagedObject:
    storage.upload_file(io.BytesIO(data), settings.STORAGE_BUCKET_NAME, key, "application/octet-stream")
    return StagedObject(key=key, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))


def _pack_archive(organization_uuid: UUID, inputs: dict[str, Any]) -> bytes:
    """Archive the installed pack that admission retained, verified by its digest."""
    digest = inputs["source"]["package_digest"]
    source = RaesPackageSource.objects.filter(organization_uuid=organization_uuid, package_digest=digest).first()
    if source is None:
        raise CMSError("The admitted pack is no longer installed")
    with _pack_snapshot(source) as root:
        if not verify_pack_digest(root, digest):
            raise CMSError("The installed pack differs from the admitted pack")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            archive.add(root, arcname=source.package_identity)
        return buffer.getvalue()


def stage_trial(
    organization_uuid: UUID, inputs: dict[str, Any], row: ExperimentEntry
) -> tuple[dict[str, StagedObject], datetime]:
    """Stage the retained trial SDL, the admitted pack and ``trial.json``."""
    storage = get_object_storage()
    prefix = f"{TRIAL_INPUT_PREFIX}{row.token}/"
    scenario = json.dumps(inputs["snapshots"][row.plan_entry_id], sort_keys=True).encode()
    pack = _pack_archive(organization_uuid, inputs)
    deadline = datetime.now(UTC) + timedelta(seconds=entry_attempt_timeout(inputs, row.plan_entry_id))
    staged = {
        "scenario.sdl": _stage_object(storage, prefix + "scenario.sdl", scenario),
        "pack.tar": _stage_object(storage, prefix + "pack.tar", pack),
    }
    trial = {
        "schema_version": "bigrae.trial-input/v1",
        "run_id": row.run_id,
        "attempt_id": str(row.token),
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
        "scenario_sha256": staged["scenario.sdl"].sha256,
        "pack_sha256": staged["pack.tar"].sha256,
    }
    staged["trial.json"] = _stage_object(storage, prefix + "trial.json", json.dumps(trial).encode())
    return staged, deadline


def _start_trial(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
) -> str:
    """Hold evidence, stage inputs and start the trial on a qualified worker."""
    from engine.services import acquire_worker_hold, get_disposable_worker, start_worker_trial

    if not get_disposable_worker(credential, worker_id).qualified:
        return "waiting-for-worker"
    acquire_worker_hold(credential, worker_id, reason=_HOLD_REASON)
    staged, deadline = stage_trial(organization_uuid, inputs, row)
    start_worker_trial(credential, worker_id, owner_reference=row.token, staged=staged, deadline=deadline)
    observe_experiment_attempt(credential, organization_uuid, row.token, "running")
    return "trial-started"


def _collect(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    archive: dict[str, Any],
) -> str:
    """Intake the sealed archive with independently derived identities."""
    expected = experiment_archive_identity(inputs, row.plan_entry_id, str(row.token))
    with tempfile.TemporaryDirectory(prefix="trial-collect-") as workdir:
        path = Path(workdir) / "archive"
        get_object_storage().download_object(
            settings.STORAGE_BUCKET_NAME, archive["key"], str(path), max_bytes=MAX_ARCHIVE_BYTES
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != archive["sha256"]:
            raise CMSError("The trial archive differs from its export report")
        with path.open("rb") as source:
            collection = intake_trial_archive(credential, organization_uuid, expected, source)
    if not collection.worker_copy_disposable:
        raise CMSError("The trial archive is not yet safe to discard from the worker")
    record_experiment_collection(credential, organization_uuid, row.token, collection.id)
    final = "finished" if collection.run_status == "completed" else "failed"
    observe_experiment_attempt(credential, organization_uuid, row.token, final)
    return "collected"


def _retire(credential: CredentialContext, worker_id: UUID) -> str:
    """Release this coordinator's evidence holds, then retire the worker."""
    from engine.services import list_worker_holds, release_worker_hold, retire_disposable_worker

    for hold in list_worker_holds(credential, worker_id):
        if hold.reason == _HOLD_REASON and not hold.released:
            release_worker_hold(credential, hold.hold_id)
    retire_disposable_worker(credential, worker_id)
    return "retiring"


def _record_cleanup(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
    run_status: str,
) -> str:
    receipt = worker_absence_cleanup_receipt(
        inputs,
        row.plan_entry_id,
        str(row.token),
        trial_outcome=_RUN_OUTCOMES.get(run_status, "aborted"),
        evidence_ref=f"worker:{worker_id}:verified-absent",
    )
    record_experiment_cleanup(credential, organization_uuid, row.token, receipt)
    return "cleanup-recorded"


def _advance(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    scope: ResourceScope,
    row: ExperimentEntry,
    *,
    collect_only: bool,
) -> tuple[str, Any]:
    """Advance one claimed entry by at most one step."""
    from engine.services import collect_worker_trial, get_disposable_worker, get_worker_trial

    if not row.worker_ref:
        return (
            ("waiting", None) if collect_only else (_create_and_report(credential, organization_uuid, scope, row), None)
        )
    worker_id = UUID(row.worker_ref.removeprefix("worker:"))
    worker = get_disposable_worker(credential, worker_id)
    try:
        trial = get_worker_trial(credential, worker_id)
    except ObjectDoesNotExist:
        trial = None
    if trial is None:
        if collect_only or worker.retiring:
            return "not-started", None
        return _start_trial(credential, organization_uuid, inputs, row, worker_id), None
    if row.receipt_id is None:
        if trial.state == "exited" and trial.archive is not None:
            return _collect(credential, organization_uuid, inputs, row, trial.archive), trial
        if trial.state == "failed" or (trial.state == "exited" and not trial.sealed):
            collect_worker_trial(credential, worker_id)
            return "collect-requested", trial
        return "running", trial
    if not worker.retiring:
        return _retire(credential, worker_id), trial
    if worker.retired and not row.cleanup_receipt_json:
        return _record_cleanup(credential, organization_uuid, inputs, row, worker_id, row.receipt.run_status), trial
    return "waiting-for-cleanup", trial


def _create_and_report(
    credential: CredentialContext, organization_uuid: UUID, scope: ResourceScope, row: ExperimentEntry
) -> str:
    try:
        _create_worker(credential, organization_uuid, scope, row)
    except ValueError:
        return "waiting-for-capacity"
    return "worker-created"


def reconcile_experiment_dispatch(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch_id: UUID,
    *,
    scope: ResourceScope,
    collect_only: bool = False,
) -> list[DispatchStep]:
    """Advance every claimed entry from its stored state; never start a second trial."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    inputs = _load(admission, batch_id).inputs
    steps = []
    for row in _entries(organization_uuid, batch_id):
        trial = None
        if row.token is None or row.cleanup_receipt_json:
            action = "none"
        else:
            action, trial = _advance(credential, organization_uuid, inputs, scope, row, collect_only=collect_only)
            row.refresh_from_db()
        steps.append(_step(row, trial, action))
    return steps


def stop_experiment_dispatch(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID
) -> list[DispatchStep]:
    """Request a stop for each running trial; collection follows through reconcile."""
    from engine.services import collect_worker_trial

    _authorize(credential, organization_uuid, "manage_content")
    steps = []
    for row in _entries(organization_uuid, batch_id):
        action = "none"
        if row.worker_ref and row.receipt_id is None:
            try:
                collect_worker_trial(credential, UUID(row.worker_ref.removeprefix("worker:")), stop=True)
                action = "stop-requested"
            except ObjectDoesNotExist:
                action = "not-started"
        steps.append(_step(row, None, action))
    return steps


def _step(row: ExperimentEntry, trial: Any, action: str) -> DispatchStep:
    return DispatchStep(
        plan_entry_id=row.plan_entry_id,
        execution_attempt_id=str(row.token) if row.token else None,
        worker_id=row.worker_ref.removeprefix("worker:") or None,
        trial_state=getattr(trial, "state", None),
        collected=row.receipt_id is not None,
        cleanup_recorded=bool(row.cleanup_receipt_json),
        action=action,
    )
