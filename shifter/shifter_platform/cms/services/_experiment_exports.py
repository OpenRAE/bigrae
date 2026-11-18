"""Organize retained trial results through their existing service owners."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from shared.credentials import CredentialContext
from shared.exceptions import CMSError
from shared.raes.experiment_admission import experiment_archive_identity
from shared.raes.experiment_dispatch_inputs import trial_scenario_sha256
from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity
from shared.raes.trial_results import TrialArchiveContents, inspect_trial_archive

from ._experiment_batch_records import RetainedExperimentBatch
from ._experiment_batches import list_experiment_entries, load_experiment_batch
from ._experiment_export_records import (
    ExperimentExportAssociationError,
    ExperimentExportDataError,
    ExperimentExportLimitError,
    _entry_row,
    _files,
    _json,
    _manifest,
    _reconcile_rows,
)
from ._trial_archives import (
    TrialArchiveCollection,
    list_trial_archives,
    publish_experiment_export,
    retrieve_trial_archive,
)

MAX_EXPORT_ENTRIES = 10000
MAX_EXPORT_ARCHIVES = 10000
MAX_EXPORT_BYTES = 128 * 1024**2


def _source_view(collection: TrialArchiveCollection) -> dict[str, Any]:
    """Identify original custody and incomplete transfers without inventing receipts."""
    receipt = collection.collection_status in {"committed", "expired"}
    return {
        "transfer_id": str(collection.transfer_id),
        "receipt_id": str(collection.id) if receipt else None,
        "archive_digest": collection.archive_digest or None,
        "expected": collection.expected,
        "collection_status": collection.collection_status,
        "failure_code": collection.failure_code or None,
        "expires_at": collection.expires_at.isoformat() if collection.expires_at else None,
        "inspection_status": "unavailable",
        "members": None,
        "run_status": collection.run_status or None,
        "outcome_status": collection.outcome_status or None,
        "evidence_complete": collection.evidence_complete if receipt else None,
        "gap_count": collection.gap_count if receipt else None,
    }


def _read_source(
    credential: CredentialContext,
    organization_uuid: UUID,
    collection: TrialArchiveCollection,
) -> TrialArchiveContents | None:
    """Read only verified retained bytes; unsupported interpretation refuses explicitly."""
    if collection.collection_status != "committed":
        return None
    with tempfile.TemporaryDirectory(prefix="experiment-source-") as temporary:
        path = Path(temporary) / "archive"
        try:
            retrieve_trial_archive(credential, organization_uuid, collection.id, path)
        except CMSError:
            # Current authority is checked again by subsequent reads and publication.
            return None
        try:
            return inspect_trial_archive(path, TrialArchiveIdentity(**collection.expected))
        except TrialArchiveError:
            raise ExperimentExportDataError("Retained archive is invalid or exceeds supported export limits") from None


def _source_rows(
    contents: TrialArchiveContents,
    source: dict[str, Any],
    assignments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retain each original run version and its exact ordered attempt history."""
    plan, run = contents.plan, contents.run
    identity = source["expected"]
    entry = plan["entries"][identity["entry_id"]]
    origin = plan.get("replacement_origin")
    base = _entry_row(plan, entry, assignments.get(entry["plan_entry_id"]), origin)
    realized = {
        key: run[key]
        for key in ("realized_bindings", "realized_selections", "participant_implementation_provenance")
        if run.get(key)
    }
    base.update(
        archive_digest=source["archive_digest"],
        run_version=run["run_version"],
        run_status=run["run_status"],
        outcome_status=run["outcome_status"],
        record_state=run["record_state"],
        entry_status=run["run_status"],
        collection_status="committed",
        archive_available=True,
        run_started_at=run["started_at"],
        run_ended_at=run.get("ended_at"),
        evidence_complete=contents.facts.evidence_complete,
        gap_count=contents.facts.gap_count,
        capture_gaps=contents.capture_gaps,
        observed_configuration=realized or None,
        usage=contents.usage or None,
        result_summaries=run.get("result_summaries") or None,
        invalidation=run.get("invalidation"),
        source_refs=[
            {
                "receipt_id": source["receipt_id"],
                "transfer_id": source["transfer_id"],
                "archive_digest": source["archive_digest"],
                "member": f"{run['run_id']}/manifest.json",
            }
        ],
    )
    accounting = run.get("execution_accounting")
    attempts = accounting["attempts"] if accounting else run["trial_provenance"]["execution_attempts"]
    return [
        dict(
            base,
            execution_attempt_id=attempt["execution_attempt_id"],
            attempt=attempt.get("attempt"),
            started_at=attempt.get("started_at"),
            ended_at=attempt.get("ended_at"),
            execution_status=attempt.get("execution_status"),
            capture_status=attempt.get("capture_status"),
            configuration_status=attempt.get("configuration_status"),
            usage=[
                value
                for value in contents.usage
                if value.get("execution_attempt_id") in {None, attempt["execution_attempt_id"]}
            ]
            or None,
        )
        for attempt in attempts
    ]


def _belongs_to_batch(plan: dict[str, Any], batch: RetainedExperimentBatch) -> bool:
    """Use retained root identities without compiling or allocating replacements."""
    root = batch.inputs["plan"]
    if plan["plan_id"] == root["plan_id"]:
        if plan["plan_digest"] != root["plan_digest"]:
            raise CMSError("Retained archive conflicts with admitted batch identity")
        return True
    origin = plan.get("replacement_origin")
    return bool(
        origin
        and origin["root_plan_id"] == root["plan_id"]
        and origin["root_plan_digest"] == root["plan_digest"]
        and origin["root_entry_id"] in root["entries"]
    )


def _unavailable_row(
    plan: dict[str, Any], source: dict[str, Any], assignments: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Keep known receipt summaries while leaving absent observations unknown."""
    expected = source["expected"]
    row = _entry_row(
        plan,
        plan["entries"][expected["entry_id"]],
        assignments.get(expected["entry_id"]),
        plan.get("replacement_origin"),
    )
    row.update(
        archive_digest=source["archive_digest"],
        run_version=expected["run_version"],
        execution_attempt_id=expected["attempt_id"],
        collection_status=source["collection_status"],
        entry_status="uncollected",
        run_status=source["run_status"],
        outcome_status=source["outcome_status"],
        evidence_complete=source["evidence_complete"],
        gap_count=source["gap_count"],
        source_refs=[
            {
                "transfer_id": source["transfer_id"],
                "receipt_id": source["receipt_id"],
                "archive_digest": source["archive_digest"],
                "member": None,
            }
        ],
    )
    return row


def _association_key(expected: dict[str, str]) -> tuple[str, ...]:
    """Join only identical immutable plan, entry and run identities."""
    return tuple(expected[key] for key in ("plan_id", "plan_digest", "entry_id", "entry_digest", "run_id"))


def _unavailable_plan(
    collection: TrialArchiveCollection,
    batch: RetainedExperimentBatch,
    associations: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any]:
    """Resolve retained allocation or verified metadata without trusting failed input."""
    expected, root = collection.expected, batch.inputs["plan"]
    if expected["plan_id"] == root["plan_id"]:
        try:
            # A trial seal binds the retained entry's trial SDL; derive its digest, never trust the record.
            scenario = (
                trial_scenario_sha256(batch.inputs, expected["entry_id"]) if "scenario_sha256" in expected else ""
            )
            correct = experiment_archive_identity(
                batch.inputs,
                expected["entry_id"],
                expected["attempt_id"],
                expected["run_version"],
                scenario_sha256=scenario,
            ).as_record()
        except (KeyError, ValueError):
            raise CMSError("Retained archive identity does not match its admitted entry") from None
        if expected != correct:
            raise CMSError("Retained archive identity does not match its admitted entry")
        return root
    plan = associations.get(_association_key(expected))
    if plan is None:
        raise ExperimentExportAssociationError("Unavailable archive association cannot be established")
    return plan


def _collection_rows(
    credential: CredentialContext,
    organization_uuid: UUID,
    collection: TrialArchiveCollection,
    batch: RetainedExperimentBatch,
    assignments: dict[str, dict[str, Any]],
    associations: dict[tuple[str, ...], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Join one original source to the admitted root or its recorded replacement."""
    source = _source_view(collection)
    contents = _read_source(credential, organization_uuid, collection)
    if contents is not None:
        if contents.facts.plan_metadata is not None:
            associations[_association_key(collection.expected)] = contents.facts.plan_metadata
        if not _belongs_to_batch(contents.plan, batch):
            return None
        source.update(
            inspection_status="verified",
            members=contents.members,
            run_record_digest=contents.facts.run_record_digest,
            run_status=contents.facts.run_status,
            outcome_status=contents.facts.outcome_status,
            evidence_complete=contents.facts.evidence_complete,
            gap_count=contents.facts.gap_count,
        )
        found = _source_rows(contents, source, assignments)
    else:
        plan = _unavailable_plan(collection, batch, associations)
        if not _belongs_to_batch(plan, batch):
            return None
        found = [] if collection.collection_status == "duplicate" else [_unavailable_row(plan, source, assignments)]
    return source, found


def _retained_collections(
    credential: CredentialContext, organization_uuid: UUID, experiment_id: str
) -> Iterator[TrialArchiveCollection]:
    """Page the owning inventory with explicit observation and metadata limits."""
    offset, metadata_bytes = 0, 0
    while True:
        page = list_trial_archives(credential, organization_uuid, experiment_id=experiment_id, offset=offset)
        offset += len(page)
        if offset > MAX_EXPORT_ARCHIVES:
            raise ExperimentExportLimitError("Experiment archive inventory exceeds its supported size limit")
        for collection in page:
            metadata_bytes += len(
                _json(
                    asdict(collection)
                    | {
                        "id": str(collection.id),
                        "transfer_id": str(collection.transfer_id),
                        "expires_at": str(collection.expires_at),
                    }
                )
            )
            if metadata_bytes > MAX_EXPORT_BYTES:
                raise ExperimentExportLimitError("Experiment inventory metadata exceeds its supported size limit")
            yield collection
        if len(page) < 100:
            return


def _append_inventory(
    result: tuple[dict[str, Any], list[dict[str, Any]]] | None,
    sources: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    metadata_bytes: int,
) -> int:
    """Keep all qualifying records or refuse the complete metadata size explicitly."""
    if result is None:
        return metadata_bytes
    source, found = result
    metadata_bytes += sum(len(_json(record)) for record in [source, *found])
    if metadata_bytes > MAX_EXPORT_BYTES:
        raise ExperimentExportLimitError("Experiment export metadata exceeds its supported size limit")
    sources.append(source)
    rows.extend(found)
    return metadata_bytes


def _inventory(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch: RetainedExperimentBatch,
    assignments: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read every bounded owner page and retain only the requested root and replacements."""
    root = batch.inputs["plan"]
    reference = root["input_refs"].get("study_ref") or root["input_refs"]["authoring_input_ref"]
    sources: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    metadata_bytes = 0
    associations: dict[tuple[str, ...], dict[str, Any]] = {}
    deferred: list[TrialArchiveCollection] = []
    for collection in _retained_collections(credential, organization_uuid, reference["ref_id"]):
        if collection.plan_metadata is not None:
            associations[_association_key(collection.expected)] = collection.plan_metadata
        try:
            result = _collection_rows(credential, organization_uuid, collection, batch, assignments, associations)
        except ExperimentExportAssociationError:
            deferred.append(collection)
            continue
        metadata_bytes = _append_inventory(result, sources, rows, metadata_bytes)
    for collection in deferred:
        result = _collection_rows(credential, organization_uuid, collection, batch, assignments, associations)
        metadata_bytes = _append_inventory(result, sources, rows, metadata_bytes)
    return sources, rows


def export_experiment_batch(
    credential: CredentialContext,
    organization_uuid: UUID,
    batch_id: UUID,
) -> dict[str, object]:
    """Publish deterministic manifest and CSV/JSON indexes to approved tenant storage."""
    batch = load_experiment_batch(credential, organization_uuid, batch_id)
    if batch.expected_trials > MAX_EXPORT_ENTRIES:
        raise ExperimentExportLimitError("Expected entries exceed the supported export size limit")
    assignments = {
        entry["plan_entry_id"]: entry for entry in list_experiment_entries(credential, organization_uuid, batch_id)
    }
    sources, rows = _inventory(credential, organization_uuid, batch, assignments)
    rows = _reconcile_rows(rows, batch, assignments)
    return publish_experiment_export(
        credential,
        organization_uuid,
        batch_id,
        _files(_manifest(batch, sources, rows), rows, max_bytes=MAX_EXPORT_BYTES),
    )
