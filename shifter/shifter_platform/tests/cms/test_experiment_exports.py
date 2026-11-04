"""Export retained synthetic archives through the authenticated management command."""

import copy
import csv
import io
import json
import shutil
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command

from shared.exceptions import CMSError
from shared.raes.trial_archive import TrialArchiveIdentity
from tests.cms.experiment_admission_fixtures import FIXTURE, admit, write_experiment_content_manifest
from tests.cms.experiment_admission_fixtures import experiment_inputs as experiment_inputs
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody
from tests.shared.raes.test_trial_archive import archive_bytes, encoded

pytestmark = pytest.mark.django_db


@pytest.fixture
def exports(experiment_inputs, monkeypatch):
    import yaml
    from raes_contracts.versions import BACKEND_OPERATION_CONTRACT_IDS

    from cms.scenarios.pack_validation import pack_digest
    from cms.services import _trial_archives

    source, root, authority = experiment_inputs[2:]
    authority["backend"]["supported_contract_versions"].extend(BACKEND_OPERATION_CONTRACT_IDS)
    authority["execution_authority"]["cleanup"]["retry_policy"]["max_attempts"] = 2
    authority["backend"]["capabilities"]["operation_supervision"] = {
        "name": "synthetic-supervision",
        "guarantees": ["cessation-evidence", "effect-observation"],
    }
    path = root / "experiments/crossed-design.exp.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["run_plan"]["replacement_policy"] = {"max_replacements": 1, "replace_on": ["failed"]}
    path.write_text(yaml.safe_dump(spec))
    write_experiment_content_manifest(root)
    source.package_digest = pack_digest(root)
    source.save(update_fields=["package_digest"])
    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    storage = _trial_archives.get_object_storage()
    monkeypatch.setattr("cms.management.commands.experiment_batch.credential_from_file", lambda path: actor.credential)
    return actor, organization, batch, storage


def collect(
    exports,
    entry_id=None,
    *,
    status="failed",
    version="1",
    attempt_id="attempt-a",
    omit=(),
    extra=None,
    plan_override=None,
    attempts=None,
):
    from cms.services import intake_trial_archive

    actor, organization, batch, _ = exports
    plan = plan_override or batch.inputs["plan"]
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
        if attempts:
            accounting["attempts"] = [
                dict(attempt, execution_attempt_id=value, attempt=index + 1) for index, value in enumerate(attempts)
            ]
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


def export(exports, *, expect_success=True):
    _, organization, batch, storage = exports
    output = io.StringIO()
    try:
        call_command(
            "experiment_batch",
            "export",
            credential_file="synthetic-proof-file",
            organization=organization.uuid,
            batch=batch.id,
            stdout=output,
        )
    except CommandError:
        if not expect_success:
            raise
        pytest.fail("An authorized retained batch export must succeed")
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
        export(exports, expect_success=False)


def test_authorization_and_destination(exports):
    from cms.models import TrialArchiveDestination

    result, _, _, _ = export(exports)
    assert result["bucket"] == "approved-test-storage"
    assert all(key.startswith("evidence/experiment-exports/") for key in result["files"].values())
    before = dict(exports[3].objects)
    exports[0].policy_principals.clear()
    with pytest.raises(CommandError):
        export(exports, expect_success=False)
    assert exports[3].objects == before
    exports[0].policy_principals.add(exports[0].identity_principal.uuid)
    TrialArchiveDestination.objects.all().delete()
    with pytest.raises(CommandError):
        export(exports, expect_success=False)
    assert exports[3].objects == before


def test_missing_chunk_inventory(exports):
    with pytest.raises(CMSError):
        collect(exports, omit=("traces/chunk-1.bin",))
    _, manifest, rows, files = export(exports)
    assert manifest["counts"]["collected_archives"] == 0
    assert any(row["collection_status"] == "pending" for row in rows)
    csv_rows = list(csv.DictReader(io.StringIO(files["csv"].decode())))
    assert len(csv_rows) == len(rows) == 64
    assert all(row["outcome_status"] is None for row in rows)


def test_cli_synthetic_archives(exports, experiment_inputs, monkeypatch):
    from django.db import transaction

    storage = exports[3]
    original_objects = dict(storage.objects)
    cases = [
        (test_reads_retained_records, {"experiment_inputs": experiment_inputs}),
        (test_mixed_outcomes_and_missing, {}),
        (test_attempts_and_duplicate_delivery, {}),
        (test_contents_and_capture_gaps, {}),
        (test_repeat_arrivals_and_limits, {}),
        (test_authorization_and_destination, {}),
        (test_missing_chunk_inventory, {}),
        (test_overlapping_attempt_history, {}),
        (test_replacement_lineage, {}),
        (test_archive_and_output_limits, {"bound": "MAX_EXPORT_ARCHIVES"}),
        (test_archive_and_output_limits, {"bound": "MAX_EXPORT_BYTES"}),
        (test_foreign_tenant_and_publication_revocation, {}),
        (test_export_retention_uses_existing_transfer_purge, {}),
        (test_inventory_filters_before_pagination, {}),
    ]
    for case, arguments in cases:
        principals = set(exports[0].policy_principals)
        point = transaction.savepoint()
        try:
            with monkeypatch.context() as scoped:
                if case in {
                    test_reads_retained_records,
                    test_repeat_arrivals_and_limits,
                    test_archive_and_output_limits,
                    test_foreign_tenant_and_publication_revocation,
                }:
                    arguments["monkeypatch"] = scoped
                case(exports, **arguments)
        finally:
            transaction.savepoint_rollback(point)
            exports[0].policy_principals = principals
            storage.objects.clear()
            storage.objects.update(original_objects)


def test_overlapping_attempt_history(exports):
    collect(exports, version="2", attempts=["attempt-a", "attempt-b"])
    collect(exports, version="1")
    _, manifest, rows, _ = export(exports)
    collected = [row for row in rows if row["source_refs"]]
    assert len(collected) == 3
    assert manifest["counts"]["attempts"] == 2
    assert manifest["counts"]["collected_archives"] == 2


def test_replacement_lineage(exports):
    from raes_contracts.contracts.admitted_trial_plan import seal_admitted_trial_entry, seal_admitted_trial_plan

    root = exports[2].inputs["plan"]
    entry_id, original = next(iter(root["entries"].items()))
    collect(exports)
    child = copy.deepcopy(root)
    child.pop("plan_digest")
    child.update(plan_id="synthetic-replacement-plan", allocation=None, isolation_proof=None)
    child["profiles"].update(compiler_profile="trial-compiler-replacement-designed-v1", allocation_profile="none")
    entry = copy.deepcopy(original)
    entry.pop("entry_digest")
    entry.update(plan_entry_id="synthetic-replacement-entry", run_id="synthetic-replacement-run")
    entry["instantiation_provenance"].update(
        plan_id=child["plan_id"], plan_entry_id=entry["plan_entry_id"], run_id=entry["run_id"]
    )
    cleanup = copy.deepcopy(root["cleanup_plans"][entry["execution_controls"]["cleanup_plan_ref"]])
    cleanup.update(
        plan_id="synthetic-replacement-cleanup", plan_entry_id=entry["plan_entry_id"], run_id=entry["run_id"]
    )
    entry["execution_controls"]["cleanup_plan_ref"] = cleanup["plan_id"]
    child["entries"] = {entry["plan_entry_id"]: seal_admitted_trial_entry(**entry).model_dump(mode="json")}
    child["cleanup_plans"] = {cleanup["plan_id"]: cleanup}
    child["admission"]["entry_count"] = 1
    child["replacement_origin"] = {
        "root_plan_id": root["plan_id"],
        "root_plan_digest": root["plan_digest"],
        "root_entry_id": entry_id,
        "ordinal": 1,
        "parent_plan_id": root["plan_id"],
        "parent_plan_digest": root["plan_digest"],
        "parent_entry_id": entry_id,
        "parent_run_id": original["run_id"],
        "parent_run_version": "1",
        "parent_run_digest": "sha256:" + "a" * 64,
        "cleanup_receipt_ref": "synthetic-parent-cleanup",
    }
    child = seal_admitted_trial_plan(**child).model_dump(mode="json")
    collect(exports, plan_override=child, attempt_id="replacement-attempt")
    _, manifest, rows, _ = export(exports)
    replacement = next(row for row in rows if row["plan_id"] == child["plan_id"])
    assert replacement["root_entry_id"] == entry_id
    assert replacement["replacement_origin"] == child["replacement_origin"]
    assert replacement["run_id"] != original["run_id"]
    assert manifest["counts"]["expected_entries"] == 64
    assert manifest["counts"]["replacement_entries"] == 1


@pytest.mark.parametrize("bound", ["MAX_EXPORT_ARCHIVES", "MAX_EXPORT_BYTES"])
def test_archive_and_output_limits(exports, monkeypatch, bound):
    collect(exports)
    before = dict(exports[3].objects)
    monkeypatch.setattr("cms.services._experiment_exports." + bound, 0)
    with pytest.raises(CommandError, match="limit"):
        export(exports, expect_success=False)
    assert exports[3].objects == before


def test_foreign_tenant_and_publication_revocation(exports, monkeypatch):
    _, _, batch, storage = exports
    output = io.StringIO()
    with pytest.raises(CommandError):
        call_command(
            "experiment_batch",
            "export",
            credential_file="synthetic-proof-file",
            organization=uuid4(),
            batch=batch.id,
            stdout=output,
        )
    assert not output.getvalue() and not storage.objects
    upload = storage.upload_file

    def revoke_after_write(file_obj, bucket, key, content_type=""):
        upload(file_obj, bucket, key, content_type)
        exports[0].policy_principals.clear()

    monkeypatch.setattr(storage, "upload_file", revoke_after_write)
    with pytest.raises(CommandError):
        export(exports, expect_success=False)
    assert not any(key.endswith("manifest.json") for _, key in storage.objects)


def test_export_retention_uses_existing_transfer_purge(exports):
    from django.utils import timezone

    from cms.models import TrialArchiveTransfer
    from cms.services import list_trial_archives, purge_trial_archives

    receipt, raw = collect(exports)
    export(exports)
    actor, organization, _, storage = exports
    derived = TrialArchiveTransfer.objects.filter(expected__artifact_kind="experiment-export")
    assert derived.count() == 3
    assert all(row.settled and row.expires_at is not None for row in derived)
    assert [row.id for row in list_trial_archives(actor.credential, organization.uuid)] == [receipt.id]
    derived.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert purge_trial_archives(actor.credential, organization.uuid) == 3
    assert list(storage.objects.values()) == [raw]


def test_inventory_filters_before_pagination(exports):
    from cms.services import intake_trial_archive, list_trial_archives
    from tests.shared.raes.test_trial_archive import expected

    receipt, _ = collect(exports)
    actor, organization, _, _ = exports
    intake_trial_archive(actor.credential, organization.uuid, expected(), io.BytesIO(archive_bytes()))
    rows = list_trial_archives(
        actor.credential, organization.uuid, experiment_id=receipt.expected["experiment_id"], limit=1
    )
    assert len(rows) == 1 and rows[0].id == receipt.id
