"""Deterministic record reconciliation and formatting for retained batch exports."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from shared.exceptions import CMSError

from ._experiment_batch_records import RetainedExperimentBatch


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
    status = {"pending": "not-started", "claimed": "claimed"}.get(state, "uncollected")
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


def _add_observation(indexed: dict[tuple[str, ...], dict[str, Any]], row: dict[str, Any]) -> None:
    """Prefer available original records and merge identical source observations."""
    key = _row_key(row)
    previous = indexed.get(key)
    if previous is None:
        indexed[key] = row
        return
    if previous["archive_available"] != row["archive_available"]:
        if row["archive_available"]:
            indexed[key] = row
        return
    if not row["archive_available"]:
        _merge_unavailable(previous, row)
        return
    if _json({k: v for k, v in previous.items() if k != "source_refs"}) != _json(
        {k: v for k, v in row.items() if k != "source_refs"}
    ):
        raise CMSError("Conflicting retained records for one run version and attempt")
    previous["source_refs"] = previous["source_refs"] + row["source_refs"]


def _reconcile_rows(
    rows: list[dict[str, Any]], batch: RetainedExperimentBatch, assignments: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge repeated source observations without merging scientific identities."""
    indexed: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        _add_observation(indexed, row)
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


def _missing_attempts(rows: list[dict[str, Any]], collected: set[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """List known attempts that have no retained original archive."""
    return sorted(
        {
            _attempt_identity(row)
            for row in rows
            if row["execution_attempt_id"] and _attempt_identity(row) not in collected
        }
    )


def _incomplete_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project original source gaps independently of scientific outcomes."""
    return [
        {key: source[key] for key in ("transfer_id", "collection_status", "inspection_status", "gap_count")}
        for source in sources
        if source["collection_status"] != "duplicate"
        and (source["inspection_status"] != "verified" or not source["evidence_complete"])
    ]


def _manifest(
    batch: RetainedExperimentBatch, sources: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize collection separately from source scientific status and capture coverage."""
    plan = batch.inputs["plan"]
    collected = {row["plan_entry_id"] for row in rows if row["plan_id"] == plan["plan_id"] and row["archive_available"]}
    missing = sorted(set(plan["entries"]) - collected)
    available = [source for source in sources if source["inspection_status"] == "verified"]
    collected_attempts = {_attempt_identity(row) for row in rows if row["archive_available"]}
    missing_attempts = _missing_attempts(rows, collected_attempts)
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
        "incomplete_sources": _incomplete_sources(sources),
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


def _files(manifest: dict[str, Any], rows: list[dict[str, Any]], *, max_bytes: int) -> dict[str, bytes]:
    """Build the complete bounded manifest and equivalent CSV/JSON indexes."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=sorted(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(value) for key, value in row.items()})
        if output.tell() > max_bytes:
            raise ExperimentExportLimitError("Experiment CSV exceeds its supported size limit")
    files = {"manifest": _json(manifest), "json": _json(rows), "csv": output.getvalue().encode()}
    if sum(map(len, files.values())) > max_bytes:
        raise ExperimentExportLimitError("Experiment export exceeds its supported size limit")
    return files
