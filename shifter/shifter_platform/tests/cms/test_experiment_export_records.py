"""Index invariants and original metadata scope without database setup."""

import copy
from uuid import uuid4

import pytest

from cms.services._experiment_batch_records import RetainedExperimentBatch
from cms.services._experiment_export_records import _csv_cell, _entry_row, _manifest, _reconcile_rows
from cms.services._experiment_exports import _source_rows
from shared.raes.trial_archive import VerifiedTrialArchive
from shared.raes.trial_results import TrialArchiveContents, _metadata


def records():
    entry = {
        "plan_entry_id": "entry",
        "run_id": "run",
        "entry_digest": "digest",
        "coordinate": {"condition_id": "condition", "replicate_id": "replicate"},
    }
    plan = {"plan_id": "plan", "plan_digest": "digest", "entries": {"entry": entry}}
    return RetainedExperimentBatch(uuid4(), {"plan": plan}), entry


def test_claim_does_not_create_execution_or_measurements():
    batch, entry = records()
    row = _entry_row(batch.inputs["plan"], entry, {"state": "claimed", "execution_attempt_id": "attempt"}, None)
    assert row["execution_attempt_id"] == "attempt"
    assert row["started_at"] is None and row["outcome_status"] is None
    assert row["usage"] is None and row["evidence_complete"] is None


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-cmd", "@SUM(A1)", "\t=1", "\r=1", "\n=1"])
def test_csv_preserves_text_as_text(value):
    assert _csv_cell(value) == "'" + value


def test_csv_unknowns_and_real_zero_are_distinct():
    assert _csv_cell(None) == ""
    assert _csv_cell(0) == "0"
    assert _csv_cell({"input_tokens": None}) == '{"input_tokens":null}'


def test_repeated_sources_do_not_duplicate_attempts():
    batch, entry = records()
    row = _entry_row(batch.inputs["plan"], entry, None, None)
    row.update(
        archive_available=True,
        archive_digest="digest",
        run_version="1",
        execution_attempt_id="attempt",
        source_refs=[{"receipt_id": "one"}],
    )
    duplicate = copy.deepcopy(row)
    duplicate["source_refs"] = [{"receipt_id": "two"}]
    result = _reconcile_rows([row, duplicate], batch, {})
    assert len(result) == 1
    assert result[0]["source_refs"] == [{"receipt_id": "one"}, {"receipt_id": "two"}]


def test_distinct_archive_observations_share_attempt_identity():
    batch, entry = records()
    first = _entry_row(batch.inputs["plan"], entry, None, None)
    first.update(archive_available=True, archive_digest="first", execution_attempt_id="attempt", run_version="1")
    second = dict(first, archive_digest="second", ended_at="later")
    rows = _reconcile_rows([first, second], batch, {})
    assert len(rows) == 2
    sources = [
        {
            "inspection_status": "verified",
            "archive_digest": digest,
            "evidence_complete": True,
            "collection_status": "committed",
            "transfer_id": digest,
            "gap_count": 0,
            "expected": {},
        }
        for digest in ("first", "second")
    ]
    manifest = _manifest(batch, sources, rows)
    assert manifest["counts"]["attempts"] == 1
    assert manifest["counts"]["collected_archives"] == 2


def test_usage_retains_attempt_scope_and_unknowns():
    usage, _ = _metadata(
        {
            "events": [
                {"execution_attempt_id": "a", "data": {"input_tokens": 2}},
                {"execution_attempt_id": "b", "data": {"input_tokens": None}},
                {"usage": {"output_tokens": 3}},
            ]
        },
        "trace.json",
    )
    assert [item["execution_attempt_id"] for item in usage] == ["a", "b", None]
    assert usage[1]["values"]["input_tokens"] is None
    assert usage[0]["pointer"] == "/events/0/data"


def test_attempt_rows_do_not_take_another_attempts_usage():
    batch, _ = records()
    run = {
        "run_id": "run",
        "run_version": "1",
        "run_status": "failed",
        "outcome_status": "not-evaluated",
        "record_state": "partial",
        "started_at": "original",
        "execution_accounting": {"attempts": [{"execution_attempt_id": "a"}, {"execution_attempt_id": "b"}]},
    }
    run["realized_selections"] = [{"retained_selection": "original"}]
    usage = [
        {"execution_attempt_id": attempt, "values": {"input_tokens": count}}
        for attempt, count in [("a", 1), ("b", 2), (None, None)]
    ]
    contents = TrialArchiveContents(
        VerifiedTrialArchive(1, "digest", "failed", "not-evaluated", False, 1), batch.inputs["plan"], run, [], [], usage
    )
    source = {
        "expected": {"entry_id": "entry"},
        "receipt_id": "receipt",
        "transfer_id": "transfer",
        "archive_digest": "digest",
    }
    rows = _source_rows(contents, source, {})
    assert [value["execution_attempt_id"] for value in rows[0]["usage"]] == ["a", None]
    assert [value["execution_attempt_id"] for value in rows[1]["usage"]] == ["b", None]
    assert rows[0]["observed_configuration"] == {"realized_selections": run["realized_selections"]}


def test_collected_entry_is_incomplete_with_an_outstanding_claim():
    batch, entry = records()
    archived = _entry_row(batch.inputs["plan"], entry, None, None)
    archived.update(archive_available=True, archive_digest="stored", execution_attempt_id="first", run_version="1")
    assignment = {"state": "claimed", "execution_attempt_id": "later"}
    outstanding = _entry_row(batch.inputs["plan"], entry, assignment, None)
    source = {
        "inspection_status": "verified",
        "collection_status": "committed",
        "archive_digest": "stored",
        "evidence_complete": True,
        "transfer_id": "stored",
        "gap_count": 0,
        "expected": {},
    }
    manifest = _manifest(batch, [source], [archived, outstanding])
    assert manifest["missing_entry_ids"] == []
    assert manifest["collection_complete"] is False
    assert manifest["missing_attempts"] == [
        {"plan_id": "plan", "plan_entry_id": "entry", "run_id": "run", "execution_attempt_id": "later"}
    ]
    assert outstanding["started_at"] is None and outstanding["outcome_status"] is None
    collected_later = dict(outstanding, archive_available=True, archive_digest="later")
    assert _manifest(batch, [source], [archived, collected_later])["collection_complete"] is True


def test_later_version_transfer_is_not_hidden_by_collected_attempt():
    batch, entry = records()
    row = _entry_row(batch.inputs["plan"], entry, None, None)
    row.update(archive_available=True, execution_attempt_id="attempt", run_version="1")
    collected = {
        "inspection_status": "verified",
        "collection_status": "committed",
        "archive_digest": "first",
        "evidence_complete": True,
        "transfer_id": "first",
        "gap_count": 0,
        "expected": {"run_version": "1", "attempt_id": "attempt"},
    }
    pending = dict(
        collected,
        inspection_status="unavailable",
        collection_status="pending",
        archive_digest="later",
        transfer_id="pending",
        expected={"run_version": "2", "attempt_id": "attempt"},
    )
    manifest = _manifest(batch, [collected, pending], [row])
    assert manifest["collection_complete"] is False
    assert manifest["missing_archives"][0]["transfer_id"] == "pending"
    arrived = dict(pending, inspection_status="verified", collection_status="committed", transfer_id="arrived")
    assert _manifest(batch, [collected, pending, arrived], [row])["collection_complete"] is True


@pytest.mark.parametrize("reverse", [False, True])
def test_unavailable_retry_keeps_receipt_summaries_and_custody_history(reverse):
    batch, entry = records()
    pending = _entry_row(batch.inputs["plan"], entry, None, None)
    pending.update(
        archive_digest="same-bytes",
        run_version="2",
        execution_attempt_id="attempt",
        collection_status="pending",
        source_refs=[{"transfer_id": "interrupted"}],
    )
    receipt = dict(
        pending,
        collection_status="expired",
        run_status="failed",
        outcome_status="not-evaluated",
        evidence_complete=False,
        gap_count=1,
        source_refs=[{"receipt_id": "retry"}],
    )
    observations = [pending, receipt]
    rows = _reconcile_rows(list(reversed(observations)) if reverse else observations, batch, {})
    assert len(rows) == 1
    assert rows[0]["collection_status"] == "expired"
    assert rows[0]["run_status"] == "failed" and rows[0]["evidence_complete"] is False
    assert len(rows[0]["source_refs"]) == 2
