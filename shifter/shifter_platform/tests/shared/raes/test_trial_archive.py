"""Real synthetic sealed exports exercise the archive trust boundary."""

import gzip
import hashlib
import io
import json
import tarfile
from importlib.resources import files

import pytest
from raes_contracts.contract_seals import seal_payload
from raes_contracts.contracts import AdmittedTrialPlanModel, ExperimentRunModel


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def records():
    """Use the released synthetic minimal plan; create a failed partial run."""
    path = files("raes_contracts").joinpath("_corpus/fixtures/plans/admitted-trial-plan-v1/valid/minimal.json")
    plan = AdmittedTrialPlanModel.model_validate(seal_payload(AdmittedTrialPlanModel, json.loads(path.read_bytes())))
    entry = next(iter(plan.entries.values()))
    run = ExperimentRunModel.model_validate(
        {
            "schema_version": "experiment-run/v1",
            "record_state": "partial",
            "run_id": entry.run_id,
            "run_version": "1",
            "task_ref": plan.input_refs.task_ref.model_dump(mode="json"),
            "scenario_snapshot_ref": {
                "ref_kind": "scenario-snapshot",
                "ref_id": "synthetic-snapshot",
                "ref_version": "1",
                "ref_digest": "sha256:" + "a" * 64,
            },
            "started_at": "2026-11-01T00:00:00Z",
            "ended_at": "2026-11-01T00:01:00Z",
            "clock_context": {
                "clock_id": "synthetic-clock",
                "authority": "synthetic",
                "time_domain": "wall-clock",
                "synchronization": "unspecified",
            },
            "run_status": "failed",
            "outcome_status": "not-evaluated",
            "stochastic_controls": [item.model_dump(mode="json") for item in plan.stochastic_controls.values()],
            "stochastic_draws": [item.model_dump(mode="json") for item in entry.stochastic_draws],
            "realized_selections": [
                item.treatment.model_dump(mode="json") for item in entry.selections if item.treatment
            ],
            "execution_accounting": {
                "plan_id": plan.plan_id,
                "plan_digest": plan.plan_digest,
                "plan_entry_id": entry.plan_entry_id,
                "entry_digest": entry.entry_digest,
                "participant_configurations": [
                    item.model_dump(mode="json") for item in entry.participant_configurations
                ],
                "attempts": [
                    {
                        "execution_attempt_id": "attempt-a",
                        "attempt": 1,
                        "started_at": "2026-11-01T00:00:00Z",
                        "ended_at": "2026-11-01T00:01:00Z",
                        "execution_status": "failed",
                        "capture_status": "partial",
                    }
                ],
            },
        }
    )
    return plan.model_dump(mode="json"), run.model_dump(mode="json")


def archive_bytes(*, extra=None, omit=(), change=None, record_change=None, media_types=None, bigrae_seal=False):
    plan, run = records()
    if record_change:
        record_change(plan, run)
    members = {
        "manifest.json": encoded(run),
        "trial/plan.json": encoded(plan),
        "traces/chunk-1.bin": b"synthetic participant trace\n",
    }
    members.update(extra or {})
    inventory = [
        {
            "path": name,
            "size_bytes": len(raw),
            "checksum": {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()},
            "media_type": (media_types or {}).get(name, "application/octet-stream"),
            "role": "manifest" if name == "manifest.json" else "evidence",
        }
        for name, raw in members.items()
    ]
    marker = {
        "schema_version": "aptl.run-seal/v1",
        "run_id": run["run_id"],
        "run_version": run["run_version"],
        "seal_state": "sealed",
        "run_status": run["run_status"],
        "outcome_status": run["outcome_status"],
        "run_record_digest": "sha256:" + hashlib.sha256(members["manifest.json"]).hexdigest(),
        "sealed_contract_versions": ["experiment-run/v1"],
        "inventory": inventory,
        "completeness": {
            "complete": False,
            "statement": "Capture failed.",
            "limitations": [{"code": "capture-loss", "detail": "Synthetic failure."}],
        },
    }
    if bigrae_seal:
        from shifter_adapter_sdk.trial import TrialSeal

        marker = TrialSeal(
            **{key: marker[key] for key in ("run_id", "run_version", "run_status", "outcome_status")},
            run_record_digest=marker["run_record_digest"],
            completeness={"complete": False, "limitations": ["Synthetic capture failure."]},
            inventory=inventory,
        ).model_dump(mode="json")
    members["seal.json"] = encoded(marker)
    if change:
        change(members, marker)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw in members.items():
            if name in omit:
                continue
            info = tarfile.TarInfo(f"{run['run_id']}/{name}")
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def expected(**overrides):
    from shared.raes.trial_archive import TrialArchiveIdentity

    plan, run = records()
    return TrialArchiveIdentity(
        **{
            "experiment_id": plan["input_refs"]["authoring_input_ref"]["ref_id"],
            "plan_id": plan["plan_id"],
            "entry_id": run["execution_accounting"]["plan_entry_id"],
            "run_id": run["run_id"],
            "attempt_id": "attempt-a",
            "plan_digest": plan["plan_digest"],
            "entry_digest": run["execution_accounting"]["entry_digest"],
            "run_version": run["run_version"],
            **overrides,
        }
    )


def test_collects_failed_partial_record_without_claiming_success(tmp_path):
    from shared.raes.trial_archive import validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes())
    result = validate_trial_archive(path, expected())
    assert result.run_status == "failed"
    assert result.outcome_status == "not-evaluated"
    assert result.evidence_complete is False
    assert result.member_count == 4


def test_collects_bigrae_sealed_partial_record(tmp_path):
    """#2861: a non-LilRAE apparatus seals a partial RAES run record with the BigRAE seal."""
    from shared.raes.trial_archive import validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(bigrae_seal=True))
    result = validate_trial_archive(path, expected())
    assert (result.run_status, result.outcome_status, result.evidence_complete) == ("failed", "not-evaluated", False)


def drop_record_state(plan, run):
    del run["record_state"]


def claim_lilrae_record(members, marker):
    marker["sealed_contract_versions"] = ["lilrae-trial-record/v1"]
    members["seal.json"] = encoded(marker)


@pytest.mark.parametrize(
    ("change", "record_change", "message"),
    [
        (None, drop_record_state, "must be partial"),
        (claim_lilrae_record, None, "Invalid BigRAE trial seal"),
        (lambda members, marker: members.update({"seal.json": encoded(marker | {"note": "x"})}), None, "Invalid"),
    ],
)
def test_bigrae_seal_refuses_archival_records_and_other_contracts(tmp_path, change, record_change, message):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(bigrae_seal=True, change=change, record_change=record_change))
    with pytest.raises(TrialArchiveError, match=message):
        validate_trial_archive(path, expected())


@pytest.mark.parametrize("fault", ["wrong-run", "corruption", "missing-chunk", "traversal", "secret"])
def test_rejects_invalid_archive_before_collection(tmp_path, fault):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    change = None
    if fault == "corruption":

        def change(members, marker):
            members["traces/chunk-1.bin"] = b"altered bytes"

    extra = {"../escape": b"unsafe"} if fault == "traversal" else {}
    if fault == "secret":
        extra = {"traces/credential.txt": b"Bearer synthetic-private-proof"}
    path = tmp_path / "archive.tar.gz"
    path.write_bytes(
        archive_bytes(extra=extra, omit=("traces/chunk-1.bin",) if fault == "missing-chunk" else (), change=change)
    )
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected(run_id="foreign-run") if fault == "wrong-run" else expected())


def test_accepts_original_exporter_checksum_document(tmp_path):
    from shared.raes.trial_archive import validate_trial_archive

    def checksum_document(members, marker):
        members["checksums.sha256"] = "".join(
            f"{hashlib.sha256(raw).hexdigest()}  {name}\n" for name, raw in sorted(members.items())
        ).encode()

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(change=checksum_document))
    assert validate_trial_archive(path, expected()).member_count == 5


@pytest.mark.parametrize("kind", ["symlink", "duplicate", "directory-collision", "oversized-pax"])
def test_rejects_unsafe_tar_metadata(tmp_path, kind):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    source = archive_bytes()
    out = io.BytesIO()
    with (
        tarfile.open(fileobj=out, mode="w:gz") as writer,
        tarfile.open(fileobj=io.BytesIO(source), mode="r:gz") as reader,
    ):
        for item in reader:
            writer.addfile(item, reader.extractfile(item))
        item = tarfile.TarInfo("run-a/link")
        if kind == "symlink":
            item.type, item.linkname = tarfile.SYMTYPE, "/etc/passwd"
        elif kind == "duplicate":
            item.name = "run-a/manifest.json"
        elif kind == "directory-collision":
            item.name = "run-a/traces"
        else:
            item.pax_headers = {"comment": "x" * (1024 * 1024 + 1)}
        writer.addfile(item)
    path = tmp_path / "unsafe.tar.gz"
    path.write_bytes(out.getvalue())
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected())


@pytest.mark.parametrize("field", ["experiment_id", "plan_id", "entry_id", "attempt_id"])
def test_every_expected_identity_is_independently_checked(tmp_path, field):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes())
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected(**{field: "another-identity"}))


def evidence_record(run_id, *, checksum):
    return {
        "schema_version": "experiment-evidence-record/v1",
        "evidence_record_id": "trace-a",
        "record_version": "1",
        "capture_spec_ref": {"ref_kind": "capture-spec", "ref_id": "capture-a", "ref_version": "1"},
        "capture_requirement_ref": "capture-trace",
        "output_contract": "synthetic-trace/v1",
        "run_ref": {"ref_kind": "run", "ref_id": run_id, "ref_version": "1"},
        "source_refs": [{"ref_kind": "other", "ref_id": "synthetic-participant", "ref_version": "1"}],
        "evidence_kind": "trace",
        "captured_at": "2026-11-01T00:00:30Z",
        "capture_window_ref": "execution",
        "raw_content": {
            "content_uri": "traces/chunk-1.bin",
            "content_checksum": {"algorithm": "sha256", "value": checksum},
        },
        "sensitivity": "restricted",
        "redaction_state": "none",
    }


@pytest.mark.parametrize("fault", ["content-checksum", "missing-record"])
def test_declared_evidence_joins_are_complete(tmp_path, fault):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    def with_evidence(plan, run):
        attempt = run["execution_accounting"]["attempts"][0]
        attempt["evidence_record_refs"] = [{"ref_kind": "evidence-record", "ref_id": "trace-a", "ref_version": "1"}]
        if fault != "missing-record":
            attempt["evidence_records"] = [evidence_record(run["run_id"], checksum="0" * 64)]

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(record_change=with_evidence))
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected())


def test_run_capture_loss_cannot_be_hidden_by_complete_seal(tmp_path):
    from shared.raes.trial_archive import validate_trial_archive

    def complete_marker(members, marker):
        marker["completeness"] = {"complete": True, "statement": "All declared bytes retained.", "limitations": []}
        members["seal.json"] = encoded(marker)

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(change=complete_marker))
    result = validate_trial_archive(path, expected())
    assert result.evidence_complete is False
    assert result.gap_count > 0


def test_large_trace_is_streamed_without_requiring_one_large_json_document(tmp_path, monkeypatch):
    from shared.raes import trial_archive

    monkeypatch.setattr(trial_archive, "MAX_JSON_BYTES", 32768)
    trace = (b'{"synthetic_trace":"' + b"a" * 100 + b'"}\n') * 2000
    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(extra={"traces/full.jsonl": trace}))
    assert trial_archive.validate_trial_archive(path, expected()).member_count == 5


@pytest.mark.parametrize(
    "fault", ["credential", "foreign-record", "foreign-attempt", "missing-byte", "bad-json", "oversized-line"]
)
def test_json_lines_are_validated_incrementally(tmp_path, monkeypatch, fault):
    from shared.raes import trial_archive

    monkeypatch.setattr(trial_archive, "MAX_JSON_BYTES", 32768)
    rows = {
        "credential": b'{"password":"synthetic-excluded-value"}\n',
        "foreign-attempt": b'{"execution_attempt_id":"foreign-attempt"}\n',
        "foreign-record": encoded(evidence_record("foreign-run", checksum="0" * 64)) + b"\n",
        "missing-byte": b'{"uri":"missing.bin","checksum":{"algorithm":"sha256","value":"' + b"0" * 64 + b'"}}\n',
        "bad-json": b'{"invalid":\n',
        "oversized-line": b'{"trace":"' + b"x" * 40000 + b'"}\n',
    }
    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(extra={"traces/participant.jsonl": rows[fault]}))
    with pytest.raises(trial_archive.TrialArchiveError):
        trial_archive.validate_trial_archive(path, expected())


def test_json_lines_scientific_records_resolve_run_evidence_references(tmp_path):
    from shared.raes.trial_archive import validate_trial_archive

    def reference(plan, run):
        run["execution_accounting"]["attempts"][0]["evidence_record_refs"] = [
            {"ref_kind": "evidence-record", "ref_id": "trace-a", "ref_version": "1"}
        ]

    raw_evidence = evidence_record(
        expected().run_id, checksum=hashlib.sha256(b"synthetic participant trace\n").hexdigest()
    )
    path = tmp_path / "archive.tar.gz"
    path.write_bytes(
        archive_bytes(extra={"traces/evidence.jsonl": encoded(raw_evidence) + b"\n"}, record_change=reference)
    )
    assert validate_trial_archive(path, expected()).member_count == 5


@pytest.mark.parametrize(
    "body",
    [b'{"schema_version":"experiment-evidence-record/v1","invalid":true}', b'{"password":"synthetic-excluded-value"}'],
)
def test_oversized_json_cannot_bypass_record_or_credential_validation(tmp_path, monkeypatch, body):
    from shared.raes import trial_archive

    monkeypatch.setattr(trial_archive, "MAX_JSON_BYTES", 32768)
    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(extra={"evidence/oversized.json": body + b" " * 40000}))
    with pytest.raises(trial_archive.TrialArchiveError):
        trial_archive.validate_trial_archive(path, expected())


def test_tar_requires_its_end_marker_even_when_all_member_bytes_are_present(tmp_path):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    raw = gzip.decompress(archive_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        end = max(member.offset_data + ((member.size + 511) // 512) * 512 for member in archive)
    path = tmp_path / "truncated.tar"
    path.write_bytes(raw[:end])
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected())


@pytest.mark.parametrize("binding", ["plan_digest", "entry_digest", "run_version"])
def test_expected_contract_versions_and_digests_are_bound(tmp_path, binding):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes())
    value = "different-version" if binding == "run_version" else "sha256:" + "0" * 64
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected(**{binding: value}))


@pytest.mark.parametrize(
    "filename,media_type,record",
    [
        ("evidence/context.json", "application/json", {"run_id": "foreign-run"}),
        ("evidence/context.json", "application/json", {"run_version": "foreign-version"}),
        ("evidence/context.json", "application/json", {"execution_attempt_id": "foreign-attempt"}),
        (
            "evidence/context.data",
            "application/json",
            {"run_ref": {"ref_kind": "run", "ref_id": "foreign-run", "ref_version": "1"}},
        ),
        ("evidence/context.data", "application/x-ndjson", {"execution_attempt_id": "foreign-attempt"}),
        ("evidence/context.data", "application/json", {"password": "synthetic-excluded-value"}),
    ],
)
def test_structured_inventory_declarations_and_bindings_are_authoritative(tmp_path, filename, media_type, record):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(archive_bytes(extra={filename: encoded(record) + b"\n"}, media_types={filename: media_type}))
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected())


def test_json_array_trace_keeps_original_bytes_and_validates_nested_bindings(tmp_path):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    current = expected()
    path = tmp_path / "archive.tar.gz"
    raw = archive_bytes(
        extra={
            "traces/events.data": encoded(
                [{"run_id": current.run_id, "execution_attempt_id": current.attempt_id, "event": "synthetic"}]
            )
        },
        media_types={"traces/events.data": "application/json"},
    )
    path.write_bytes(raw)
    assert validate_trial_archive(path, current).member_count == 5
    assert path.read_bytes() == raw
    path.write_bytes(
        archive_bytes(
            extra={"traces/events.data": encoded([{"run_id": "foreign-run"}])},
            media_types={"traces/events.data": "application/json"},
        )
    )
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, current)


SCENARIO = "sha256:" + "5" * 64


def trial_record_archive(
    *, run_id=None, record_run_id=None, attempt_id="attempt-a", limitations=(), scenario=SCENARIO, extra=None
):
    """A LilRAE trial seal: a lab-start manifest and a trial record, no RAES plan."""
    _plan, run = records()
    run_id = run_id or run["run_id"]
    members = {
        "manifest.json": encoded({"schema_version": "aptl.run-record/v2", "run_id": run_id}),
        "trial/record.json": encoded(
            {
                "schema_version": "lilrae-trial-record/v1",
                "run_id": record_run_id or run_id,
                "attempt_id": attempt_id,
                "scenario_sha256": scenario,
            }
        ),
        **(extra or {}),
    }
    marker = {
        "schema_version": "aptl.run-seal/v1",
        "run_id": run_id,
        "run_version": run["run_version"],
        "seal_state": "sealed",
        "run_status": "aborted" if limitations else "completed",
        "outcome_status": "not-evaluated",
        "run_record_digest": "sha256:" + hashlib.sha256(members["manifest.json"]).hexdigest(),
        "sealed_contract_versions": ["lilrae-trial-record/v1"],
        "inventory": [
            {
                "path": name,
                "size_bytes": len(raw),
                "checksum": {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()},
                "media_type": "application/json",
                "role": "manifest" if name == "manifest.json" else "trial-record",
            }
            for name, raw in members.items()
        ],
        "completeness": {"complete": not limitations, "statement": "Every file.", "limitations": list(limitations)},
    }
    members["seal.json"] = encoded(marker)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw in members.items():
            info = tarfile.TarInfo(f"{run_id}/{name}")
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def test_lilrae_trial_seal_binds_the_expected_attempt(tmp_path):
    from shared.raes.trial_archive import TrialArchiveError, validate_trial_archive

    path = tmp_path / "archive.tar.gz"
    path.write_bytes(trial_record_archive())
    with pytest.raises(TrialArchiveError):
        validate_trial_archive(path, expected())  # A trial seal needs the admitted scenario digest.
    result = validate_trial_archive(path, expected(scenario_sha256=SCENARIO))
    assert (result.run_status, result.evidence_complete, result.plan_metadata) == ("completed", True, None)
    path.write_bytes(trial_record_archive(limitations=[{"code": "partial-trial", "detail": "Stopped."}]))
    partial = validate_trial_archive(path, expected(scenario_sha256=SCENARIO))
    assert (partial.run_status, partial.evidence_complete, partial.gap_count) == ("aborted", False, 1)
    foreign = {"evidence/record.json": encoded({"run_id": expected().run_id, "execution_attempt_id": "attempt-b"})}
    for wrong in (
        trial_record_archive(attempt_id="attempt-b"),
        trial_record_archive(record_run_id="other-run"),
        trial_record_archive(scenario="sha256:" + "6" * 64),
        trial_record_archive(extra=foreign),
    ):
        path.write_bytes(wrong)
        with pytest.raises(TrialArchiveError):
            validate_trial_archive(path, expected(scenario_sha256=SCENARIO))
