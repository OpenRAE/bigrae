"""Export retained synthetic archives through the authenticated management command."""

import csv
import io
import json
import shutil

import pytest
from django.core.management import CommandError, call_command

from shared.exceptions import CMSError
from shared.raes.trial_archive import TrialArchiveIdentity
from tests.cms.experiment_admission_fixtures import FIXTURE, admit
from tests.cms.experiment_admission_fixtures import experiment_inputs as experiment_inputs
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody
from tests.shared.raes.test_trial_archive import archive_bytes, encoded

pytestmark = pytest.mark.django_db


@pytest.fixture
def exports(experiment_inputs, monkeypatch):
    from cms.services import _trial_archives

    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    storage = _trial_archives.get_object_storage()
    monkeypatch.setattr("cms.management.commands.experiment_batch.credential_from_file", lambda path: actor.credential)
    return actor, organization, batch, storage


def collect(exports, entry_id=None, *, status="failed", version="1", attempt_id="attempt-a", omit=(), extra=None):
    from cms.services import intake_trial_archive

    actor, organization, batch, _ = exports
    plan = batch.inputs["plan"]
    entry_id = entry_id or next(iter(plan["entries"]))
    entry = plan["entries"][entry_id]
    reference = plan["input_refs"].get("study_ref") or plan["input_refs"]["authoring_input_ref"]
    identity = TrialArchiveIdentity(
        reference["ref_id"],
        plan["plan_id"],
        entry_id,
        entry["run_id"],
        attempt_id,
        plan["plan_digest"],
        entry["entry_digest"],
        version,
    )

    def replace(original_plan, run):
        original_plan.clear()
        original_plan.update(plan)
        run.update(
            run_id=entry["run_id"],
            run_version=version,
            task_ref=plan["input_refs"]["task_ref"],
            stochastic_controls=list(plan["stochastic_controls"].values()),
            stochastic_draws=entry["stochastic_draws"],
            realized_selections=[item["treatment"] for item in entry["selections"] if item.get("treatment")],
            run_status=status,
        )
        accounting = run["execution_accounting"]
        accounting.update(
            plan_id=plan["plan_id"],
            plan_digest=plan["plan_digest"],
            plan_entry_id=entry_id,
            entry_digest=entry["entry_digest"],
            participant_configurations=entry["participant_configurations"],
        )
        attempt = accounting["attempts"][0]
        attempt["execution_attempt_id"] = attempt_id
        attempt["execution_status"] = {"completed": "succeeded", "in-progress": "running"}.get(status, "failed")
        if status == "in-progress":
            run["ended_at"] = attempt["ended_at"] = None
        if status == "invalidated":
            run["invalidation"] = {"invalidated_at": "2026-11-01T00:01:00Z", "reason": "Synthetic invalidation"}

    captures = {f"specs/{key}.capture.json": encoded(value) for key, value in batch.inputs["capture_specs"].items()}
    captures["docs/protocol.md"] = (FIXTURE / "pack/docs/protocol.md").read_bytes()
    captures.update(extra or {})
    raw = archive_bytes(record_change=replace, extra=captures, omit=omit)
    receipt = intake_trial_archive(actor.credential, organization.uuid, identity, io.BytesIO(raw))
    return receipt, raw


def export(exports):
    _, organization, batch, storage = exports
    output = io.StringIO()
    call_command(
        "experiment_batch",
        "export",
        credential_file="synthetic-proof-file",
        organization=organization.uuid,
        batch=batch.id,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    files = {name: storage.objects[(result["bucket"], key)] for name, key in result["files"].items()}
    return result, json.loads(files["manifest"]), json.loads(files["json"]), files


def test_reads_retained_records(exports, experiment_inputs, monkeypatch):
    receipt, _ = collect(exports)
    shutil.rmtree(experiment_inputs[3])
    monkeypatch.setattr(
        "shared.raes.experiment_admission.compile_pack_experiment", lambda *a, **k: pytest.fail("No compilation")
    )
    _, manifest, rows, _ = export(exports)
    assert manifest["batch_id"] == str(exports[2].id)
    assert manifest["counts"]["expected_entries"] == 64
    assert len({row["root_entry_id"] for row in rows}) == 64
    assert manifest["sources"][0]["receipt_id"] == str(receipt.id)


def test_mixed_outcomes_and_missing(exports):
    from cms.services import claim_experiment_entry, record_experiment_worker

    entries = list(exports[2].inputs["plan"]["entries"])
    for entry, status in zip(entries, ["completed", "failed", "invalidated", "in-progress"], strict=False):
        collect(exports, entry, status=status)
    actor, organization, batch, _ = exports
    claim = claim_experiment_entry(actor.credential, organization.uuid, batch.id, entries[4])
    record_experiment_worker(actor.credential, organization.uuid, claim.token, "synthetic-worker")
    _, manifest, rows, _ = export(exports)
    by_entry = {row["plan_entry_id"]: row for row in rows}
    assert {by_entry[key]["run_status"] for key in entries[:4]} == {"completed", "failed", "invalidated", "in-progress"}
    assert by_entry[entries[4]]["assignment"]["worker_ref"] == "synthetic-worker"
    assert by_entry[entries[4]]["started_at"] is None
    assert by_entry[entries[4]]["outcome_status"] is None
    assert by_entry[entries[5]]["entry_status"] == "not-started"
    assert by_entry[entries[0]]["evidence_complete"] is False
    assert manifest["collection_complete"] is False


def test_attempts_and_duplicate_delivery(exports):
    receipt, raw = collect(exports)
    from cms.services import intake_trial_archive

    actor, organization, _, _ = exports
    again = intake_trial_archive(
        actor.credential, organization.uuid, TrialArchiveIdentity(**receipt.expected), io.BytesIO(raw)
    )
    assert again.id == receipt.id
    collect(exports, version="2", attempt_id="attempt-b")
    _, manifest, rows, _ = export(exports)
    collected = [row for row in rows if row["source_refs"]]
    assert {row["execution_attempt_id"] for row in collected} == {"attempt-a", "attempt-b"}
    assert {row["run_version"] for row in collected} == {"1", "2"}
    assert manifest["counts"]["attempts"] == 2
    assert manifest["counts"]["collected_archives"] == 2


def test_contents_and_capture_gaps(exports):
    receipt, raw = collect(
        exports, extra={"usage/accounting.json": encoded({"input_tokens": 100, "output_tokens": None})}
    )
    original_objects = dict(exports[3].objects)
    _, manifest, rows, _ = export(exports)
    source = next(row for row in manifest["sources"] if row["receipt_id"] == str(receipt.id))
    assert any(member["path"].endswith("traces/chunk-1.bin") for member in source["members"])
    row = next(row for row in rows if row["source_refs"])
    assert row["gap_count"] > 0 and row["capture_gaps"]
    assert row["usage"][0]["values"] == {"input_tokens": 100, "output_tokens": None}
    assert row["usage"][0]["member"] == "usage/accounting.json"
    assert all(exports[3].objects[key] == value for key, value in original_objects.items())
    assert raw in exports[3].objects.values()


def test_repeat_arrivals_and_limits(exports, monkeypatch):
    first = export(exports)
    assert export(exports)[3] == first[3]
    collect(exports, next(reversed(exports[2].inputs["plan"]["entries"])))
    second = export(exports)
    assert second[3] != first[3]
    assert export(exports)[3] == second[3]
    monkeypatch.setattr("cms.services._experiment_exports.MAX_EXPORT_ENTRIES", 1)
    with pytest.raises(CommandError, match="limit"):
        export(exports)


def test_authorization_and_destination(exports):
    from cms.models import TrialArchiveDestination

    result, _, _, _ = export(exports)
    assert result["bucket"] == "approved-test-storage"
    assert all(key.startswith("evidence/experiment-exports/") for key in result["files"].values())
    before = dict(exports[3].objects)
    exports[0].policy_principals.clear()
    with pytest.raises(CommandError):
        export(exports)
    assert exports[3].objects == before
    exports[0].policy_principals.add(exports[0].identity_principal.uuid)
    TrialArchiveDestination.objects.all().delete()
    with pytest.raises(CommandError):
        export(exports)
    assert exports[3].objects == before


def test_cli_synthetic_archives(exports):
    with pytest.raises(CMSError):
        collect(exports, omit=("traces/chunk-1.bin",))
    _, manifest, rows, files = export(exports)
    assert manifest["counts"]["collected_archives"] == 0
    assert any(row["collection_status"] == "pending" for row in rows)
    csv_rows = list(csv.DictReader(io.StringIO(files["csv"].decode())))
    assert len(csv_rows) == len(rows) == 64
    assert all(row["outcome_status"] is None for row in rows)
