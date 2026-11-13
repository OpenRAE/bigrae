"""Run a retained experiment batch: one disposable worker for each admitted trial.

Each step reuses its owning service. Batch claims bound the concurrency, Engine
admits worker capacity, holds preserve evidence, archive intake records custody,
and retirement verifies provider absence. The coordinator keeps no state outside
those services, so a restart continues from them. It never starts a second
trial for an entry. A failed entry gets a fresh trial only when the
experiment's replacement policy authorizes it.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from cms.models import ExperimentEntry
from shared.cloud import get_object_storage
from shared.exceptions import CMSError
from shared.raes.experiment_admission import experiment_archive_identity
from shared.raes.experiment_dispatch_inputs import (
    entry_attempt_timeout,
    trial_scenario_bytes,
    trial_scenario_sha256,
    trial_unit_bytes,
    worker_absence_cleanup_receipt,
)
from shared.worker_trial import MAX_ARCHIVE_BYTES, TRIAL_INPUT_PREFIX, StagedObject

from ._experiment_authority import _authorize
from ._experiment_batches import (
    _load,
    claim_experiment_entry,
    observe_experiment_attempt,
    record_experiment_cleanup,
    record_experiment_collection,
    record_experiment_worker,
)
from ._experiment_dispatch_state import experiment_dispatch_stopped, reserve_trial_deadline, stop_experiment_batch
from ._experiment_replacement import rerun_failed_entry
from ._trial_archives import intake_trial_archive

if TYPE_CHECKING:
    from engine.services import WorkerTrialView, WorkerView
    from shared.cloud.types import ObjectStorage
    from shared.credentials import CredentialContext
    from shared.identity_scope import ResourceScope

logger = logging.getLogger(__name__)

_WORKER_NAMESPACE = uuid5(NAMESPACE_URL, "bigrae:experiment-worker")
_HOLD_REASON = "evidence"
_WORKER_REF_PREFIX = "worker:"
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
    """Return the batch's entries in plan order."""
    return list(
        ExperimentEntry.objects.filter(batch_id=batch_id, organization_uuid=organization_uuid).order_by("plan_entry_id")
    )


def _worker_id(row: ExperimentEntry) -> UUID:
    """Return the worker bound to the entry's attempt."""
    return UUID(row.worker_ref.removeprefix(_WORKER_REF_PREFIX))


def _attempt_token(row: ExperimentEntry) -> UUID:
    """Return the claimed entry's attempt identity; a pending entry has none."""
    if row.token is None:
        raise CMSError("The experiment entry has no attempt")
    return row.token


def _create_worker(
    credential: CredentialContext, organization_uuid: UUID, scope: ResourceScope, row: ExperimentEntry
) -> UUID:
    """Create or replay the attempt's worker and bind it to the attempt."""
    from engine.services import create_disposable_worker

    token = _attempt_token(row)
    worker_id = worker_id_for(token)
    create_disposable_worker(credential, scope=scope, worker_id=worker_id, experiment_id=row.batch_id, trial_id=token)
    record_experiment_worker(credential, organization_uuid, token, f"{_WORKER_REF_PREFIX}{worker_id}")
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


def _stage_object(storage: ObjectStorage, key: str, data: bytes) -> StagedObject:
    """Create one staged object, or reuse an identical one that a concurrent stager created."""
    bucket = settings.STORAGE_BUCKET_NAME
    digest = hashlib.sha256(data).hexdigest()
    if storage.object_exists(bucket, key):
        with tempfile.TemporaryDirectory(prefix="trial-stage-") as workdir:
            path = Path(workdir) / "existing"
            identity = storage.head_object(bucket, key)
            storage.download_object(bucket, key, str(path), max_bytes=len(data), expected_identity=identity)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise CMSError("A staged trial input conflicts with the attempt's inputs")
    else:
        storage.upload_file(io.BytesIO(data), bucket, key, "application/octet-stream")
    return StagedObject(key=key, sha256=digest, size_bytes=len(data))


def stage_trial(
    credential: CredentialContext, organization_uuid: UUID, inputs: dict[str, Any], row: ExperimentEntry
) -> tuple[dict[str, StagedObject], datetime]:
    """Stage the trial unit, scenario, and control input for the worker runtime.

    The attempt's deadline is persisted first, so every stager produces the same bytes.
    """
    token = _attempt_token(row)
    deadline = reserve_trial_deadline(
        credential, organization_uuid, token, entry_attempt_timeout(inputs, row.plan_entry_id)
    )
    storage = get_object_storage()
    prefix = f"{TRIAL_INPUT_PREFIX}{token}/"
    scenario_bytes = trial_scenario_bytes(inputs, row.plan_entry_id)
    unit = _stage_object(
        storage, prefix + "trial-unit.json", trial_unit_bytes(inputs, row.plan_entry_id, scenario_bytes)
    )
    scenario = _stage_object(storage, prefix + "scenario.sdl", scenario_bytes)
    trial = {
        "schema_version": "bigrae.trial-input/v1",
        "run_id": row.run_id,
        "attempt_id": str(token),
        "deadline": deadline.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "unit_sha256": unit.sha256,
        "scenario_sha256": scenario.sha256,
    }
    encoded = json.dumps(trial, sort_keys=True, separators=(",", ":")).encode()
    return {
        "trial-unit.json": unit,
        "scenario.sdl": scenario,
        "trial.json": _stage_object(storage, prefix + "trial.json", encoded),
    }, deadline


def _hold_evidence(credential: CredentialContext, worker_id: UUID) -> None:
    """Hold the worker once for this coordinator."""
    from engine.services import acquire_worker_hold, list_worker_holds

    if not any(hold.reason == _HOLD_REASON for hold in list_worker_holds(credential, worker_id)):
        acquire_worker_hold(credential, worker_id, reason=_HOLD_REASON)


def _worker_blocker(credential: CredentialContext, worker_id: UUID) -> str | None:
    """Return why the worker cannot start a trial yet; qualify a ready worker first."""
    from engine.services import get_disposable_worker, qualify_disposable_worker

    worker = get_disposable_worker(credential, worker_id)
    blocker = None
    if worker.status != "ready":
        blocker = "waiting-for-worker"
    elif not worker.qualified:
        try:
            qualify_disposable_worker(credential, worker_id)
        except ValueError:
            blocker = "qualification-failed"
    return blocker


def _start_trial(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
) -> str:
    """Qualify the worker, hold evidence, stage inputs and start the trial."""
    from engine.services import collect_worker_trial, start_worker_trial

    if experiment_dispatch_stopped(organization_uuid, row.batch_id):
        return "stopped"
    blocker = _worker_blocker(credential, worker_id)
    if blocker is not None:
        return blocker
    _hold_evidence(credential, worker_id)
    staged, deadline = stage_trial(credential, organization_uuid, inputs, row)
    token = _attempt_token(row)
    start_worker_trial(credential, worker_id, owner_reference=token, staged=staged, deadline=deadline)
    observe_experiment_attempt(credential, organization_uuid, token, "running")
    if experiment_dispatch_stopped(organization_uuid, row.batch_id):
        # A stop committed while this trial was starting: stop it too.
        collect_worker_trial(credential, worker_id, stop=True)
    return "trial-started"


def _collect(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    archive: dict[str, Any],
) -> str:
    """Intake the sealed archive with independently derived identities."""
    token = _attempt_token(row)
    scenario = trial_scenario_sha256(inputs, row.plan_entry_id)
    expected = experiment_archive_identity(inputs, row.plan_entry_id, str(token), scenario_sha256=scenario)
    with tempfile.TemporaryDirectory(prefix="trial-collect-") as workdir:
        path = Path(workdir) / "archive"
        storage = get_object_storage()
        identity = storage.head_object(settings.STORAGE_BUCKET_NAME, archive["key"])
        storage.download_object(
            settings.STORAGE_BUCKET_NAME,
            archive["key"],
            str(path),
            max_bytes=MAX_ARCHIVE_BYTES,
            expected_identity=identity,
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != archive["sha256"]:
            raise CMSError("The trial archive differs from its export report")
        with path.open("rb") as source:
            collection = intake_trial_archive(credential, organization_uuid, expected, source, run_record_only=True)
    if not collection.worker_copy_disposable:
        raise CMSError("The trial archive is not yet safe to discard from the worker")
    record_experiment_collection(credential, organization_uuid, token, collection.id, scenario_sha256=scenario)
    # A completed run with a gap in its required trial data is a failed trial.
    final = "finished" if collection.run_status == "completed" and collection.evidence_complete else "failed"
    observe_experiment_attempt(credential, organization_uuid, token, final)
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
    """Record the verified-absence cleanup receipt for the retired worker."""
    token = _attempt_token(row)
    receipt = worker_absence_cleanup_receipt(
        inputs,
        row.plan_entry_id,
        str(token),
        trial_outcome=_RUN_OUTCOMES.get(run_status, "aborted"),
        evidence_ref=f"{_WORKER_REF_PREFIX}{worker_id}:verified-absent",
    )
    record_experiment_cleanup(credential, organization_uuid, token, receipt)
    return "cleanup-recorded"


def _advance(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    scope: ResourceScope,
    row: ExperimentEntry,
    *,
    collect_only: bool,
) -> tuple[str, WorkerTrialView | None]:
    """Advance one claimed entry by at most one step."""
    from engine.services import get_disposable_worker, get_worker_trial

    if not row.worker_ref:
        action = "waiting" if collect_only else _create_and_report(credential, organization_uuid, scope, row)
        return action, None
    worker_id = _worker_id(row)
    worker = get_disposable_worker(credential, worker_id)
    try:
        trial = get_worker_trial(credential, worker_id)
    except ObjectDoesNotExist:
        if row.state == "failed" or worker.status in {"failed", "destroying", "destroyed"} or worker.retiring:
            action = _advance_failed_setup(credential, organization_uuid, inputs, row, worker_id, worker)
        elif collect_only:
            action = "not-started"
        else:
            action = _start_trial(credential, organization_uuid, inputs, row, worker_id)
        return action, None
    return _advance_started(credential, organization_uuid, inputs, row, worker_id, worker, trial), trial


def _advance_failed_setup(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
    worker: WorkerView,
) -> str:
    """Retain setup failure, then use normal retirement and verified cleanup."""
    if row.state != "failed":
        action = _fail_uncollected(credential, organization_uuid, row, "worker-setup-failed")
    elif worker.retired:
        action = _record_cleanup(credential, organization_uuid, inputs, row, worker_id, "failed")
    elif not worker.retiring:
        action = _retire(credential, worker_id)
    else:
        action = "waiting-for-cleanup"
    return action


def _advance_started(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
    worker: WorkerView,
    trial: WorkerTrialView,
) -> str:
    """Collect the started trial, then retire its worker, then record cleanup.

    A trial that ended without a collectable archive is a failed attempt with no data.
    """
    receipt = row.receipt
    if receipt is None and row.state != "failed":
        action = _advance_collection(credential, organization_uuid, inputs, row, worker_id, trial)
    elif not worker.retiring:
        action = _retire(credential, worker_id)
    elif worker.retired and not row.cleanup_receipt_json:
        run_status = receipt.run_status if receipt is not None else "failed"
        action = _record_cleanup(credential, organization_uuid, inputs, row, worker_id, run_status)
    else:
        action = "waiting-for-cleanup"
    return action


def _advance_collection(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    worker_id: UUID,
    trial: WorkerTrialView,
) -> str:
    """Collect a sealed run, or recover collection without starting another trial."""
    from engine.services import collect_worker_trial

    if trial.state == "exited" and trial.archive is not None:
        action = _collect(credential, organization_uuid, inputs, row, trial.archive)
    elif not trial.operation_finished:
        action = "running"
        if trial.overdue:
            collect_worker_trial(credential, worker_id, stop=True)
            action = "recovery-requested"
    elif trial.state == "prepared":
        action = _fail_uncollected(credential, organization_uuid, row, "start-failed")
    elif trial.state == "exited" and trial.operation == "collect" and not trial.operation_failed:
        action = _fail_uncollected(credential, organization_uuid, row, "not-sealed")
    elif trial.overdue and trial.operation == "collect":
        # Past its deadline and drain, and the recovery collection still found no archive.
        action = _fail_uncollected(credential, organization_uuid, row, "no-archive")
    else:
        collect_worker_trial(credential, worker_id)
        action = "collect-requested"
    return action


def _fail_uncollected(credential: CredentialContext, organization_uuid: UUID, row: ExperimentEntry, cause: str) -> str:
    """Record a failed attempt without a collectable trial archive."""
    observe_experiment_attempt(credential, organization_uuid, _attempt_token(row), "failed")
    return cause


def _create_and_report(
    credential: CredentialContext, organization_uuid: UUID, scope: ResourceScope, row: ExperimentEntry
) -> str:
    """Create the attempt's worker, or report that worker capacity is exhausted."""
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
        trial: WorkerTrialView | None = None
        try:
            if row.token is None:
                action = _dispatch_replacement(credential, organization_uuid, scope, row, collect_only=collect_only)
            elif row.cleanup_receipt_json:
                action = rerun_failed_entry(credential, organization_uuid, inputs, row)
            else:
                action, trial = _advance(credential, organization_uuid, inputs, scope, row, collect_only=collect_only)
        except (CMSError, ValueError) as exc:
            # One entry's failure must not stop the other entries' progress.
            logger.warning("experiment dispatch entry=%s failed reason=%s", row.plan_entry_id, str(exc)[:200])
            action = "error"
        row.refresh_from_db()
        steps.append(_step(row, trial, action))
    return steps


def _dispatch_replacement(
    credential: CredentialContext,
    organization_uuid: UUID,
    scope: ResourceScope,
    row: ExperimentEntry,
    *,
    collect_only: bool,
) -> str:
    """Claim a pending replacement entry and create its worker; original entries wait for ``start``."""
    if row.replaces_id is None or collect_only or experiment_dispatch_stopped(organization_uuid, row.batch_id):
        return "none"
    if claim_experiment_entry(credential, organization_uuid, row.batch_id, row.plan_entry_id) is None:
        return "waiting-for-capacity"
    row.refresh_from_db()
    return _create_and_report(credential, organization_uuid, scope, row)


def stop_experiment_dispatch(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID
) -> list[DispatchStep]:
    """Request a stop for each running trial; collection follows through reconcile."""
    from engine.services import collect_worker_trial

    stop_experiment_batch(credential, organization_uuid, batch_id)
    steps = []
    for row in _entries(organization_uuid, batch_id):
        action = "none"
        if row.worker_ref and row.receipt_id is None:
            try:
                collect_worker_trial(credential, _worker_id(row), stop=True)
                action = "stop-requested"
            except ObjectDoesNotExist:
                action = "not-started"
        steps.append(_step(row, None, action))
    return steps


def _step(row: ExperimentEntry, trial: WorkerTrialView | None, action: str) -> DispatchStep:
    """Project one entry's observed position after this pass."""
    return DispatchStep(
        plan_entry_id=row.plan_entry_id,
        execution_attempt_id=str(row.token) if row.token else None,
        worker_id=row.worker_ref.removeprefix(_WORKER_REF_PREFIX) or None,
        trial_state=None if trial is None else trial.state,
        collected=row.receipt_id is not None,
        cleanup_recorded=bool(row.cleanup_receipt_json),
        action=action,
    )
