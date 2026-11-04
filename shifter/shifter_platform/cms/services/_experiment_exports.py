"""Organize retained trial results through their existing service owners."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from shared.credentials import CredentialContext
from shared.exceptions import CMSError
from shared.raes.experiment_admission import experiment_archive_identity
from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity
from shared.raes.trial_results import TrialArchiveContents, inspect_trial_archive

from ._experiment_batch_records import RetainedExperimentBatch
from ._experiment_batches import list_experiment_entries, load_experiment_batch
from ._trial_archives import (
    TrialArchiveCollection,
    list_trial_archives,
    publish_experiment_export,
    retrieve_trial_archive,
)

MAX_EXPORT_ENTRIES = 10000
MAX_EXPORT_ARCHIVES = 10000
MAX_EXPORT_BYTES = 128 * 1024**2


class ExperimentExportLimitError(CMSError):
    """The complete export cannot fit within a supported bound."""


class ExperimentExportAssociationError(CMSError):
    """An unavailable collection cannot be associated with a retained root."""


class ExperimentExportDataError(CMSError):
    """Retained original bytes are invalid or exceed supported inspection bounds."""


def _json(value: object) -> bytes:
    """Serialize derived indexes deterministically without changing source contracts."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()


def _entry_row(
    plan: dict[str, Any], entry: dict[str, Any], assignment: dict[str, Any] | None, origin: dict[str, Any] | None
) -> dict[str, Any]:
    """Keep allocation and assignment facts separate from unknown execution facts."""
    coordinate = entry["coordinate"]
    state = assignment["state"] if assignment else "pending"
    status = "not-started" if state == "pending" else "claimed" if state == "claimed" else "uncollected"
    return {
        "root_entry_id": origin["root_entry_id"] if origin else entry["plan_entry_id"],
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "plan_entry_id": entry["plan_entry_id"],
        "entry_digest": entry["entry_digest"],
        "condition_id": coordinate.get("condition_id"),
        "block_id": coordinate.get("block_id"),
        "replicate_id": coordinate["replicate_id"],
        "run_id": entry["run_id"],
        "run_version": None,
        "archive_digest": None,
        "execution_attempt_id": assignment["execution_attempt_id"] if assignment else None,
        "attempt": None,
        "assignment": assignment,
        "entry_status": status,
        "run_status": None,
        "outcome_status": None,
        "record_state": None,
        "execution_status": None,
        "started_at": None,
        "ended_at": None,
        "run_started_at": None,
        "run_ended_at": None,
        "capture_status": None,
        "configuration_status": None,
        "collection_status": "uncollected",
        "archive_available": False,
        "evidence_complete": None,
        "gap_count": None,
        "capture_gaps": [],
        "selected_configuration": entry.get("participant_configurations"),
        "selected_bindings": entry.get("bindings"),
        "selected_selections": entry.get("selections"),
        "observed_configuration": None,
        "usage": None,
        "result_summaries": None,
        "replacement_origin": origin,
        "invalidation": None,
        "source_refs": [],
    }


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
            correct = asdict(
                experiment_archive_identity(
                    batch.inputs, expected["entry_id"], expected["attempt_id"], expected["run_version"]
                )
            )
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
        if result is None:
            continue
        source, found = result
        for record in [source, *found]:
            metadata_bytes += len(_json(record))
            if metadata_bytes > MAX_EXPORT_BYTES:
                raise ExperimentExportLimitError("Experiment export metadata exceeds its supported size limit")
        sources.append(source)
        rows.extend(found)
    for collection in deferred:
        result = _collection_rows(credential, organization_uuid, collection, batch, assignments, associations)
        if result is not None:
            source, found = result
            metadata_bytes += len(_json([source, *found]))
            if metadata_bytes > MAX_EXPORT_BYTES:
                raise ExperimentExportLimitError("Experiment export metadata exceeds its supported size limit")
            sources.append(source)
            rows.extend(found)
    return sources, rows


def _row_key(row: dict[str, Any]) -> tuple[str, ...]:
    """Order versions and attempts by identity, independently of arrival order."""
    return tuple(
        str(row[key] or "")
        for key in ("plan_id", "plan_entry_id", "run_id", "run_version", "execution_attempt_id", "archive_digest")
    )


def _merge_unavailable(previous: dict[str, Any], row: dict[str, Any]) -> None:
    """Combine custody observations, preserving known scientific summaries and conflicts."""
    for key, value in row.items():
        if key in {"source_refs", "collection_status"} or value is None:
            continue
        if previous[key] is not None and previous[key] != value:
            raise CMSError("Conflicting retained records for one run version and attempt")
        previous[key] = value
    if row["collection_status"] in {"committed", "expired"}:
        previous["collection_status"] = row["collection_status"]
    previous["source_refs"] = previous["source_refs"] + row["source_refs"]


def _reconcile_rows(
    rows: list[dict[str, Any]], batch: RetainedExperimentBatch, assignments: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge repeated source observations without merging scientific identities."""
    indexed: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = _row_key(row)
        previous = indexed.get(key)
        if previous and previous["archive_available"] and not row["archive_available"]:
            continue
        if previous and not previous["archive_available"] and not row["archive_available"]:
            _merge_unavailable(previous, row)
        elif previous and previous["archive_available"] == row["archive_available"]:
            if _json({k: v for k, v in previous.items() if k != "source_refs"}) != _json(
                {k: v for k, v in row.items() if k != "source_refs"}
            ):
                raise CMSError("Conflicting retained records for one run version and attempt")
            previous["source_refs"] = previous["source_refs"] + row["source_refs"]
        else:
            indexed[key] = row
    plan = batch.inputs["plan"]
    represented = {(row["plan_id"], row["plan_entry_id"]) for row in indexed.values()}
    attempts = {(row["plan_entry_id"], row["execution_attempt_id"]) for row in indexed.values()}
    for key, entry in plan["entries"].items():
        assignment = assignments.get(key)
        unrepresented_claim = (
            assignment
            and assignment["execution_attempt_id"]
            and (key, assignment["execution_attempt_id"]) not in attempts
        )
        if (plan["plan_id"], key) not in represented or unrepresented_claim:
            row = _entry_row(plan, entry, assignment, None)
            indexed[_row_key(row)] = row
    result = sorted(indexed.values(), key=_row_key)
    for row in result:
        row["source_refs"] = sorted(row["source_refs"], key=lambda ref: _json(ref))
    return result


_ATTEMPT_FIELDS = ("plan_id", "plan_entry_id", "run_id", "execution_attempt_id")


def _attempt_identity(row: dict[str, Any]) -> tuple[str, ...]:
    """Identify an execution attempt independently of its retained archive observations."""
    return tuple(row[field] for field in _ATTEMPT_FIELDS)


def _missing_archives(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep unresolved versions visible even after another version of the attempt arrives."""
    available: dict[bytes, set[str]] = {}
    for source in sources:
        if source["inspection_status"] == "verified":
            available.setdefault(_json(source["expected"]), set()).add(source["archive_digest"])
    missing = []
    for source in sources:
        if source["inspection_status"] == "verified" or source["collection_status"] == "duplicate":
            continue
        peers = available.get(_json(source["expected"]), set())
        resolved = bool(peers) and (not source["archive_digest"] or source["archive_digest"] in peers)
        if source["collection_status"] in {"committed", "expired"} or not resolved:
            missing.append({key: source[key] for key in ("transfer_id", "archive_digest", "expected")})
    return sorted(missing, key=lambda source: source["transfer_id"])


def _manifest(
    batch: RetainedExperimentBatch, sources: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize collection separately from source scientific status and capture coverage."""
    plan = batch.inputs["plan"]
    collected = {row["plan_entry_id"] for row in rows if row["plan_id"] == plan["plan_id"] and row["archive_available"]}
    missing = sorted(set(plan["entries"]) - collected)
    available = [source for source in sources if source["inspection_status"] == "verified"]
    collected_attempts = {_attempt_identity(row) for row in rows if row["archive_available"]}
    missing_attempts = sorted(
        {
            _attempt_identity(row)
            for row in rows
            if row["execution_attempt_id"] and _attempt_identity(row) not in collected_attempts
        }
    )
    missing_archives = _missing_archives(sources)
    return {
        "schema_version": "bigrae.experiment-export/v1",
        "batch_id": str(batch.id),
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "counts": {
            "expected_entries": len(plan["entries"]),
            "collected_entries": len(collected),
            "missing_entries": len(missing),
            "collected_archives": len({s["archive_digest"] for s in available}),
            "attempts": len(collected_attempts),
            "missing_attempts": len(missing_attempts),
            "replacement_entries": len({r["plan_entry_id"] for r in rows if r["replacement_origin"]}),
            "duplicate_deliveries": sum(s["collection_status"] == "duplicate" for s in sources),
        },
        "collection_complete": not (missing or missing_attempts or missing_archives),
        "collected_capture_complete": all(s["evidence_complete"] for s in available) if available else None,
        "missing_entry_ids": missing,
        "missing_archives": missing_archives,
        "missing_attempts": [dict(zip(_ATTEMPT_FIELDS, identity, strict=True)) for identity in missing_attempts],
        "incomplete_sources": [
            {
                "transfer_id": s["transfer_id"],
                "collection_status": s["collection_status"],
                "inspection_status": s["inspection_status"],
                "gap_count": s["gap_count"],
            }
            for s in sources
            if s["collection_status"] != "duplicate"
            and (s["inspection_status"] != "verified" or not s["evidence_complete"])
        ],
        "sources": sorted(sources, key=lambda source: source["transfer_id"]),
    }


def _csv_cell(value: object) -> str:
    """Preserve unknowns and prevent strings from becoming spreadsheet formulas."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _json(value).decode().rstrip("\n")
    text = str(value)
    return "'" + text if isinstance(value, str) and text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


def _files(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, bytes]:
    """Build the complete bounded manifest and equivalent CSV/JSON indexes."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=sorted(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(value) for key, value in row.items()})
        if output.tell() > MAX_EXPORT_BYTES:
            raise ExperimentExportLimitError("Experiment CSV exceeds its supported size limit")
    files = {"manifest": _json(manifest), "json": _json(rows), "csv": output.getvalue().encode()}
    if sum(map(len, files.values())) > MAX_EXPORT_BYTES:
        raise ExperimentExportLimitError("Experiment export exceeds its supported size limit")
    return files


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
        credential, organization_uuid, batch_id, _files(_manifest(batch, sources, rows), rows)
    )
