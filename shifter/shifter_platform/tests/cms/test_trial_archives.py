"""Tenant custody through real services and synthetic original archive bytes."""

import io
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from shared.cloud.exceptions import CloudStorageError
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_tenant_pack_upload import PackStorage
from tests.shared.raes.test_trial_archive import archive_bytes, encoded, evidence_record, expected

pytestmark = pytest.mark.django_db


@pytest.fixture
def custody(tenant, monkeypatch):
    from cms.services import configure_trial_archive_destination

    actor, organization = tenant
    actor.policy_accounts.add(None)
    configure_trial_archive_destination(
        actor.credential, organization.uuid, bucket="approved-test-storage", prefix="evidence", retention_days=30
    )
    actor.policy_accounts.discard(None)
    storage = PackStorage()
    monkeypatch.setattr("cms.services._trial_archives.get_object_storage", lambda: storage)
    return actor, organization, storage


def collect(custody, raw=None):
    from cms.services import intake_trial_archive

    actor, organization, _ = custody
    return intake_trial_archive(actor.credential, organization.uuid, expected(), io.BytesIO(raw or archive_bytes()))


def test_verified_receipt_preserves_original_archive_and_failed_outcome(custody, tmp_path):
    from cms.services import retrieve_trial_archive

    actor, organization, storage = custody
    raw = archive_bytes()
    receipt = collect(custody, raw)
    assert receipt.worker_copy_disposable
    assert receipt.run_status == "failed"
    assert receipt.evidence_complete is False
    assert list(storage.objects.values()) == [raw]
    target = tmp_path / "download.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw


def test_interrupted_transfer_is_visible_retryable_and_never_a_receipt(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt, TrialArchiveTransfer
    from cms.services import list_trial_archives
    from shared.exceptions import CMSError

    actor, organization, storage = custody
    original = storage.upload_file

    def interrupted(file_obj, bucket, key, content_type=""):
        original(file_obj, bucket, key, content_type)
        raise CloudStorageError("synthetic lost acknowledgement")

    monkeypatch.setattr(storage, "upload_file", interrupted)
    with pytest.raises(CMSError, match="retry"):
        collect(custody)
    assert not TrialArchiveReceipt.objects.exists()
    assert TrialArchiveTransfer.objects.get().failure_code == "transfer-unverified"
    assert list_trial_archives(actor.credential, organization.uuid)[0].worker_copy_disposable is False
    monkeypatch.setattr(storage, "upload_file", original)
    receipt = collect(custody)
    assert receipt.worker_copy_disposable
    assert len(storage.objects) == 2


def test_duplicate_is_idempotent_changed_bytes_conflict(custody):
    from shared.exceptions import CMSError

    raw = archive_bytes()
    first = collect(custody, raw)
    second = collect(custody, raw)
    assert second.id == first.id
    assert len(custody[2].objects) == 1
    with pytest.raises(CMSError, match="conflict"):
        collect(custody, archive_bytes(extra={"traces/additional.bin": b"different original bytes"}))
    assert len(custody[2].objects) == 1


def test_destination_corruption_never_publishes(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    storage = custody[2]
    original = storage.upload_file

    def corrupt(file_obj, bucket, key, content_type=""):
        original(file_obj, bucket, key, content_type)
        storage.objects[(bucket, key)] += b"corruption"

    monkeypatch.setattr(storage, "upload_file", corrupt)
    with pytest.raises(CMSError):
        collect(custody)
    assert not TrialArchiveReceipt.objects.exists()


def test_foreign_or_denied_operations_do_not_access_storage(custody, tmp_path):
    from cms.services import intake_trial_archive, list_trial_archives, retrieve_trial_archive
    from shared.exceptions import CMSError

    actor, organization, storage = custody
    receipt = collect(custody)
    actor.policy_principals.clear()
    with pytest.raises(CMSError):
        list_trial_archives(actor.credential, organization.uuid)
    with pytest.raises(CMSError):
        retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, tmp_path / "denied")
    with pytest.raises(CMSError):
        intake_trial_archive(actor.credential, uuid4(), expected(), io.BytesIO(archive_bytes()))
    assert len(storage.objects) == 1
    assert not (tmp_path / "denied").exists()


def test_retention_denies_reads_before_purge_and_preserves_tombstone(custody, tmp_path):
    from cms.models import TrialArchiveReceipt
    from cms.services import purge_trial_archives, retrieve_trial_archive
    from shared.exceptions import CMSError

    actor, organization, storage = custody
    raw = archive_bytes()
    receipt = collect(custody, raw)
    TrialArchiveReceipt.objects.filter(pk=receipt.id).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(CMSError):
        retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, tmp_path / "expired")
    assert purge_trial_archives(actor.credential, organization.uuid) == 1
    assert not storage.objects
    assert TrialArchiveReceipt.objects.get(pk=receipt.id).state == "expired"
    assert collect(custody, raw).worker_copy_disposable is False


def test_destination_requires_explicit_operator_approval(tenant):
    from cms.services import configure_trial_archive_destination, intake_trial_archive
    from shared.exceptions import CMSError

    actor, organization = tenant
    with pytest.raises(CMSError):
        configure_trial_archive_destination(
            actor.credential, organization.uuid, bucket="test-approved", prefix="evidence", retention_days=30
        )
    with pytest.raises(CMSError, match="not configured"):
        intake_trial_archive(actor.credential, organization.uuid, expected(), io.BytesIO(archive_bytes()))


def test_revoked_during_upload_cannot_publish(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    actor, _organization, storage = custody
    original = storage.upload_file

    def revoked(file_obj, bucket, key, content_type=""):
        original(file_obj, bucket, key, content_type)
        actor.policy_principals.clear()

    monkeypatch.setattr(storage, "upload_file", revoked)
    with pytest.raises(CMSError):
        collect(custody)
    assert not TrialArchiveReceipt.objects.exists()
    assert len(storage.objects) == 1


def test_invalid_collection_is_visible_as_a_gap_without_upload(custody):
    from cms.services import list_trial_archives
    from shared.exceptions import CMSError

    with pytest.raises(CMSError):
        collect(custody, archive_bytes(omit=("traces/chunk-1.bin",)))
    actor, organization, storage = custody
    row = list_trial_archives(actor.credential, organization.uuid)[0]
    assert row.failure_code == "invalid-archive"
    assert not row.worker_copy_disposable
    assert row.gap_count > 0
    assert not storage.objects


def test_failed_retention_deletion_is_retryable(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt
    from cms.services import purge_trial_archives

    actor, organization, storage = custody
    receipt = collect(custody)
    TrialArchiveReceipt.objects.filter(pk=receipt.id).update(expires_at=timezone.now() - timedelta(seconds=1))
    original = storage.delete_object
    monkeypatch.setattr(storage, "delete_object", lambda *args: (_ for _ in ()).throw(CloudStorageError("unavailable")))
    assert purge_trial_archives(actor.credential, organization.uuid) == 0
    assert storage.objects
    monkeypatch.setattr(storage, "delete_object", original)
    assert purge_trial_archives(actor.credential, organization.uuid) == 1


def test_command_uses_the_same_intake_service(custody, monkeypatch, tmp_path):

    from django.core.management import call_command

    actor, organization, _ = custody
    monkeypatch.setattr("cms.management.commands.trial_archive.credential_from_file", lambda path: actor.credential)
    archive = tmp_path / "trial.tar.gz"
    raw = archive_bytes()
    archive.write_bytes(raw)
    output = io.StringIO()
    ids = expected()
    call_command(
        "trial_archive",
        "intake",
        credential_file="synthetic-private-proof-file",
        organization=organization.uuid,
        archive=str(archive),
        experiment=ids.experiment_id,
        plan=ids.plan_id,
        entry=ids.entry_id,
        run=ids.run_id,
        attempt=ids.attempt_id,
        plan_digest=ids.plan_digest,
        entry_digest=ids.entry_digest,
        run_version=ids.run_version,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["worker_copy_disposable"] is True
    assert collect(custody, raw).id == uuid4().__class__(result["id"])


def test_same_size_destination_corruption_is_not_checksum_proof(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    storage = custody[2]
    original = storage.upload_file

    def corrupt(file_obj, bucket, key, content_type=""):
        original(file_obj, bucket, key, content_type)
        raw = storage.objects[(bucket, key)]
        storage.objects[(bucket, key)] = bytes([raw[0] ^ 1]) + raw[1:]

    monkeypatch.setattr(storage, "upload_file", corrupt)
    with pytest.raises(CMSError):
        collect(custody)
    assert not TrialArchiveReceipt.objects.exists()


def test_committed_object_version_is_pinned_for_retrieval(custody, monkeypatch, tmp_path):
    from cms.services import retrieve_trial_archive
    from shared.exceptions import CMSError

    actor, organization, storage = custody
    receipt = collect(custody)
    original = storage.head_object

    def changed_version(bucket, key):
        return {**original(bucket, key), "etag": "another-object-version"}

    monkeypatch.setattr(storage, "head_object", changed_version)
    with pytest.raises(CMSError):
        retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, tmp_path / "archive")
    assert not (tmp_path / "archive").exists()


def test_lost_receipt_response_replays_the_committed_identity(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt
    from cms.services import _trial_archives
    from shared.exceptions import CMSError

    original = _trial_archives._publish

    def lost_response(*args):
        original(*args)
        raise CloudStorageError("response lost after receipt commit")

    raw = archive_bytes()
    monkeypatch.setattr(_trial_archives, "_publish", lost_response)
    with pytest.raises(CMSError):
        collect(custody, raw)
    committed = TrialArchiveReceipt.objects.get()
    monkeypatch.setattr(_trial_archives, "_publish", original)
    assert collect(custody, raw).id == committed.id
    assert len(custody[2].objects) == 1


def test_configuration_changes_do_not_redirect_committed_custody(custody, tmp_path):
    from cms.models import TrialArchiveReceipt
    from cms.services import configure_trial_archive_destination, retrieve_trial_archive

    actor, organization, storage = custody
    raw = archive_bytes()
    receipt = collect(custody, raw)
    actor.policy_accounts.add(None)
    configure_trial_archive_destination(
        actor.credential, organization.uuid, bucket="other-approved-storage", prefix="new-prefix", retention_days=None
    )
    actor.policy_accounts.discard(None)
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, tmp_path / "original")
    assert (tmp_path / "original").read_bytes() == raw
    assert TrialArchiveReceipt.objects.get(pk=receipt.id).expires_at is not None
    assert {bucket for bucket, key in storage.objects} == {"approved-test-storage"}


def test_purge_advances_past_already_purged_receipts(custody):
    from cms.models import TrialArchiveReceipt
    from cms.services import intake_trial_archive, purge_trial_archives

    actor, organization, storage = custody
    collect(custody)
    intake_trial_archive(
        actor.credential,
        organization.uuid,
        expected(attempt_id="attempt-b"),
        io.BytesIO(
            archive_bytes(
                record_change=lambda plan, run: run["execution_accounting"]["attempts"][0].update(
                    execution_attempt_id="attempt-b"
                )
            )
        ),
    )
    TrialArchiveReceipt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert purge_trial_archives(actor.credential, organization.uuid, limit=1) == 1
    assert purge_trial_archives(actor.credential, organization.uuid, limit=1) == 1
    assert not storage.objects


def test_retention_fences_a_verified_but_unpublished_writer(custody, monkeypatch):
    from cms.models import TrialArchiveReceipt, TrialArchiveTransfer
    from cms.services import purge_trial_archives
    from shared.exceptions import CMSError

    actor, organization, storage = custody
    original = storage.download_object

    def verified_then_expired(*args, **kwargs):
        identity = original(*args, **kwargs)
        TrialArchiveTransfer.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert purge_trial_archives(actor.credential, organization.uuid) == 1
        return identity

    monkeypatch.setattr(storage, "download_object", verified_then_expired)
    with pytest.raises(CMSError):
        collect(custody)
    assert not TrialArchiveReceipt.objects.exists()
    assert TrialArchiveTransfer.objects.get().state == "purged"
    assert not storage.objects


@pytest.mark.parametrize(
    "record",
    [
        {"run_ref": {"ref_kind": "run", "ref_id": "foreign-run", "ref_version": "1"}},
        {
            "raw_content": {
                "content_uri": "traces/missing-chunk.bin",
                "content_checksum": {"algorithm": "sha256", "value": "0" * 64},
            }
        },
    ],
)
def test_json_lines_cannot_hide_foreign_records_or_missing_bytes(custody, record):

    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    raw = archive_bytes(extra={"traces/participant.jsonl": json.dumps(record).encode() + b"\n"})
    with pytest.raises(CMSError):
        collect(custody, raw)
    assert not TrialArchiveReceipt.objects.exists()
    assert not custody[2].objects


def test_valid_large_json_lines_trace_remains_collectible(custody, monkeypatch):
    from shared.raes import trial_archive

    monkeypatch.setattr(trial_archive, "MAX_JSON_BYTES", 32768)
    trace = (b'{"participant":"synthetic","output":"' + b"x" * 200 + b'"}\n') * 10000
    raw = archive_bytes(extra={"traces/full.jsonl": trace})
    receipt = collect(custody, raw)
    assert receipt.worker_copy_disposable
    assert list(custody[2].objects.values()) == [raw]


def test_complete_declared_evidence_round_trip_preserves_optional_unavailable(custody, tmp_path):
    import tarfile

    from cms.services import retrieve_trial_archive

    actor, organization, storage = custody
    identity = expected()
    run_ref = {"ref_kind": "run", "ref_id": identity.run_id, "ref_version": identity.run_version}
    optional = evidence_record(identity.run_id, checksum="0" * 64)
    optional.update(
        evidence_record_id="optional-service-a", redaction_state="withheld", redaction_policy="synthetic-policy/v1"
    )
    optional["raw_content"] = {
        "payload_summary": "Optional service unavailable.",
        "loss_disclosure": "Service not enabled for this trial.",
    }
    extras = {
        "sdl/hydrated.sdl.yaml": b"name: synthetic-trial\nnodes: {}\n",
        "provenance/source.json": encoded({"run_ref": run_ref, "source_digest": "sha256:" + "a" * 64}),
        "participants/config.json": encoded({"run_ref": run_ref, "configuration": {"participant": "synthetic"}}),
        "participants/prompt.json": encoded(
            {
                "run_ref": run_ref,
                "prompt_commitment": "sha256:" + "b" * 64,
                "authorized_content": "Synthetic instructions.",
            }
        ),
        "traces/participant.jsonl": encoded(
            {
                "run_ref": run_ref,
                "execution_attempt_id": identity.attempt_id,
                "message": "Synthetic participant action.",
            }
        )
        + b"\n",
        "traces/tools.data": encoded({"run_ref": run_ref, "tool": "synthetic-tool", "output": "Synthetic tool result."})
        + b"\n",
        "security/export.data": encoded({"run_ref": run_ref, "observations": ["synthetic-event"]}),
        "security/packets.bin": b"synthetic packet capture\x00\x01",
        "realization/native.json": encoded({"run_ref": run_ref, "observed": ["synthetic-resource-present"]}),
        "usage/accounting.json": encoded({"run_ref": run_ref, "input_tokens": 100, "output_tokens": 20}),
        "capture/loss.json": encoded({"run_ref": run_ref, "loss_disclosure": "One optional capture was unavailable."}),
        "cleanup/accounting.json": encoded(
            {"run_ref": run_ref, "execution_attempt_id": identity.attempt_id, "cleanup_status": "unobserved"}
        ),
        "evidence/optional.json": encoded(optional),
    }
    media_types = {name: "application/json" for name in extras if name.endswith(".json")}
    media_types.update({"traces/tools.data": "application/x-ndjson", "security/export.data": "application/json"})
    raw = archive_bytes(extra=extras, media_types=media_types)
    receipt = collect(custody, raw)
    target = tmp_path / "complete.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw == next(iter(storage.objects.values()))
    with tarfile.open(target) as archive:
        for name, original in extras.items():
            assert archive.extractfile(f"{identity.run_id}/{name}").read() == original
    assert receipt.worker_copy_disposable
    assert receipt.run_status == "failed"
    assert not receipt.evidence_complete
    assert receipt.gap_count > 0


@pytest.mark.parametrize(
    "filename,media_type",
    [("evidence/nested.json", "application/json"), ("traces/nested.data", "application/x-ndjson")],
)
@pytest.mark.parametrize(
    "record",
    [
        {"events": [{"run_ref": {"ref_kind": "run", "ref_id": "foreign-run", "ref_version": "1"}}]},
        {"events": [{"execution_attempt_id": "foreign-attempt"}]},
        {"events": [{"context": {"run_version": "foreign-version"}}]},
    ],
)
def test_nested_structured_foreign_records_never_upload(custody, filename, media_type, record):
    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    raw = archive_bytes(extra={filename: encoded(record) + b"\n"}, media_types={filename: media_type})
    with pytest.raises(CMSError):
        collect(custody, raw)
    assert not TrialArchiveReceipt.objects.exists()
    assert not custody[2].objects


@pytest.mark.parametrize(
    "filename,media_type",
    [("evidence/history.json", "application/json"), ("traces/history.data", "application/x-ndjson")],
)
def test_historical_references_are_preserved_without_claiming_current_ownership(custody, filename, media_type):
    record = {
        "source_refs": [{"ref_kind": "run", "ref_id": "historical-run", "ref_version": "prior-version"}],
        "events": [{"run_id": expected().run_id, "execution_attempt_id": expected().attempt_id}],
    }
    raw = archive_bytes(extra={filename: encoded(record) + b"\n"}, media_types={filename: media_type})
    assert collect(custody, raw).worker_copy_disposable
    assert next(iter(custody[2].objects.values())) == raw


@pytest.mark.parametrize(
    "filename,media_type", [("sdl/hydrated.sdl.yaml", "application/yaml"), ("evidence/config.data", "text/yaml")]
)
@pytest.mark.parametrize(
    "content",
    [b"configuration:\n  password: synthetic-planted-value\n", b"participant:\n  api_key: synthetic-planted-value\n"],
)
def test_yaml_scenario_credentials_are_preserved_in_the_receipted_archive(custody, filename, media_type, content):
    raw = archive_bytes(extra={filename: content}, media_types={filename: media_type})
    assert collect(custody, raw).worker_copy_disposable
    assert next(iter(custody[2].objects.values())) == raw


def test_json_lines_scenario_credentials_are_preserved_in_the_receipted_archive(custody):
    raw = archive_bytes(extra={"traces/participant.jsonl": b'{"password": "synthetic-planted-value"}\n'})
    assert collect(custody, raw).worker_copy_disposable
    assert next(iter(custody[2].objects.values())) == raw


@pytest.mark.parametrize("schema", ["experiment-evidence-record/v1", "experiment-run/v1", "trial-cleanup-receipt/v1"])
def test_nested_json_lines_scientific_records_use_released_validation(custody, schema):
    from cms.models import TrialArchiveReceipt
    from shared.exceptions import CMSError

    line = {"events": [{"scientific_record": {"schema_version": schema}}]}
    raw = archive_bytes(
        extra={"records/nested.data": encoded(line) + b"\n"},
        media_types={"records/nested.data": "application/x-ndjson"},
    )
    with pytest.raises(CMSError):
        collect(custody, raw)
    assert not TrialArchiveReceipt.objects.exists()
    assert not custody[2].objects


def test_nested_json_lines_evidence_resolves_before_receipt_commit(custody, tmp_path):
    import hashlib

    from cms.services import retrieve_trial_archive

    record = evidence_record(expected().run_id, checksum=hashlib.sha256(b"synthetic participant trace\n").hexdigest())
    line = {"events": [{"scientific_record": record}]}

    def reference(plan, run):
        run["execution_accounting"]["attempts"][0]["evidence_record_refs"] = [
            {"ref_kind": "evidence-record", "ref_id": "trace-a", "ref_version": "1"}
        ]

    raw = archive_bytes(
        extra={"records/nested.data": encoded(line) + b"\n"},
        media_types={"records/nested.data": "application/x-ndjson"},
        record_change=reference,
    )
    receipt = collect(custody, raw)
    assert receipt.worker_copy_disposable
    actor, organization, _ = custody
    target = tmp_path / "nested.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw


def test_empty_required_capture_is_an_explicit_gap(custody, tmp_path):
    import hashlib

    from cms.services import retrieve_trial_archive

    identity = expected()
    specification = required_capture_specification(identity)
    record = evidence_record(identity.run_id, checksum=hashlib.sha256(b"").hexdigest())
    record["output_contract"] = "participant-behavior-history-event-stream-v1"
    record["raw_content"]["content_uri"] = "traces/required.jsonl"
    raw = archive_bytes(
        extra={
            "capture/spec.json": encoded(specification.model_dump(mode="json")),
            "capture/record.json": encoded(record),
            "traces/required.jsonl": b"",
        }
    )
    receipt = collect(custody, raw)
    assert not receipt.evidence_complete
    # The original partial-run disclosure is one gap. Empty required bytes
    # must add a distinct capture gap instead of relying on that disclosure.
    assert receipt.gap_count >= 2
    actor, organization, _ = custody
    target = tmp_path / "empty-capture.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw


def required_capture_specification(identity):
    from raes_contracts.contracts import ExperimentCaptureSpecModel

    return ExperimentCaptureSpecModel.model_validate(
        {
            "schema_version": "experiment-capture-spec/v1",
            "capture_spec_id": "capture-a",
            "spec_version": "1",
            "title": "Required participant trace",
            "description": "Synthetic required trace capture.",
            "scope_refs": [{"ref_kind": "run", "ref_id": identity.run_id, "ref_version": identity.run_version}],
            "capture_windows": [{"window_id": "execution", "window_kind": "run", "starts_at": "2026-11-01T00:00:00Z"}],
            "capture_requirements": {
                "capture-trace": {
                    "requirement_id": "capture-trace",
                    "title": "Participant trace",
                    "capture_kind": "trace",
                    "capture_scope": "participant",
                    "channel_ref": {"ref_kind": "measurement-channel", "ref_id": "channel-a", "ref_version": "1"},
                    "window_refs": ["execution"],
                    "expected_media_types": ["application/jsonl"],
                    "output_contract": "participant-behavior-history-event-stream-v1",
                    "field_selectors": ["/0"],
                    "sensitivity": "restricted",
                    "integrity_requirements": ["sha256-digest"],
                }
            },
        }
    )


@pytest.mark.parametrize("second_capture", ["missing", "empty", "present", "unavailable", "shared"])
def test_required_capture_coverage_is_per_attempt(custody, tmp_path, second_capture):
    import hashlib

    from raes_contracts.contracts import AdmittedTrialPlanModel, seal_admitted_trial_plan

    from cms.services import intake_trial_archive, retrieve_trial_archive

    identity = expected()
    first_bytes = encoded({"run_id": identity.run_id, "execution_attempt_id": "attempt-a"}) + b"\n"
    second_bytes = encoded({"run_id": identity.run_id, "execution_attempt_id": "attempt-b"}) + b"\n"
    first = evidence_record(identity.run_id, checksum=hashlib.sha256(first_bytes).hexdigest())
    first["output_contract"] = "participant-behavior-history-event-stream-v1"
    first["raw_content"]["content_uri"] = "traces/first.jsonl"
    extra = {
        "capture/spec.json": encoded(required_capture_specification(identity).model_dump(mode="json")),
        "capture/first.json": encoded(first),
        "traces/first.jsonl": first_bytes,
    }
    if second_capture in {"empty", "present", "unavailable"}:
        payload = b"" if second_capture == "empty" else second_bytes
        second = evidence_record(identity.run_id, checksum=hashlib.sha256(payload).hexdigest())
        second.update(evidence_record_id="trace-b", output_contract=first["output_contract"])
        second["captured_at"] = "2026-11-01T00:00:45Z"
        second["raw_content"]["content_uri"] = "traces/second.jsonl"
        if second_capture == "unavailable":
            second["raw_content"] = {"payload_summary": "Optional source unavailable", "loss_disclosure": "No source"}
        else:
            extra["traces/second.jsonl"] = payload
        extra["capture/second.json"] = encoded(second)

    def two_attempts(plan, run):
        # The public sealer recomputes the digest after the admitted retry change.
        original_plan = AdmittedTrialPlanModel.model_validate(plan)
        fields = {
            name: getattr(original_plan, name) for name in type(original_plan).model_fields if name != "plan_digest"
        }
        cleanup = original_plan.cleanup_plans["cleanup-a"]
        cleanup_data = cleanup.model_dump(mode="json")
        cleanup_data["retry_policy"]["max_attempts"] = 2
        fields["cleanup_plans"] = {"cleanup-a": type(cleanup).model_validate(cleanup_data)}
        sealed = seal_admitted_trial_plan(**fields)
        plan.update(sealed.model_dump(mode="json"))
        run["execution_accounting"]["plan_digest"] = sealed.plan_digest
        nonlocal identity
        identity = expected(plan_digest=sealed.plan_digest)
        first_attempt = run["execution_accounting"]["attempts"][0]
        first_attempt.update(ended_at="2026-11-01T00:00:30Z", capture_status="complete")
        first_attempt["evidence_record_refs"] = [
            {"ref_kind": "evidence-record", "ref_id": "trace-a", "ref_version": "1"}
        ]
        second_attempt = {
            **first_attempt,
            "execution_attempt_id": "attempt-b",
            "attempt": 2,
            "started_at": "2026-11-01T00:00:31Z",
            "ended_at": "2026-11-01T00:01:00Z",
            "evidence_record_refs": [],
        }
        if second_capture != "missing":
            second_attempt["evidence_record_refs"] = [
                {
                    "ref_kind": "evidence-record",
                    "ref_id": "trace-a" if second_capture == "shared" else "trace-b",
                    "ref_version": "1",
                }
            ]
        run["execution_accounting"]["attempts"].append(second_attempt)

    raw = archive_bytes(extra=extra, record_change=two_attempts)
    actor, organization, _ = custody
    receipt = intake_trial_archive(actor.credential, organization.uuid, identity, io.BytesIO(raw))
    assert not receipt.evidence_complete
    if second_capture in {"missing", "empty", "shared"}:
        assert receipt.gap_count >= 2
    else:
        assert receipt.gap_count == 1  # The retained partial-run or unavailable disclosure.
    actor, organization, _ = custody
    target = tmp_path / "multi-attempt.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw


@pytest.mark.parametrize(
    ("captured_at", "gap"),
    [
        ("2026-10-31T23:59:30Z", True),
        ("2026-11-01T00:01:30Z", True),
        ("2026-11-01T00:00:19Z", True),
        ("2026-11-01T00:00:41Z", True),
        ("2026-11-01T00:00:30Z", False),
    ],
)
def test_single_attempt_capture_outside_interval_remains_a_gap(custody, tmp_path, captured_at, gap):
    import hashlib

    from cms.services import retrieve_trial_archive

    identity = expected()
    specification = required_capture_specification(identity).model_dump(mode="json")
    specification["capture_windows"][0].update(starts_at="2026-11-01T00:00:20Z", ends_at="2026-11-01T00:00:40Z")
    payload = encoded({"run_id": identity.run_id, "execution_attempt_id": identity.attempt_id}) + b"\n"
    record = evidence_record(identity.run_id, checksum=hashlib.sha256(payload).hexdigest())
    record.update(captured_at=captured_at, output_contract="participant-behavior-history-event-stream-v1")
    record["raw_content"]["content_uri"] = "traces/required.jsonl"
    raw = archive_bytes(
        extra={
            "capture/spec.json": encoded(specification),
            "capture/record.json": encoded(record),
            "traces/required.jsonl": payload,
        }
    )
    receipt = collect(custody, raw)
    assert not receipt.evidence_complete
    assert receipt.gap_count == (2 if gap else 1)
    actor, organization, _ = custody
    target = tmp_path / "capture-interval.tar.gz"
    retrieve_trial_archive(actor.credential, organization.uuid, receipt.id, target)
    assert target.read_bytes() == raw
