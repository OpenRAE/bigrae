"""Installed public contracts admit a synthetic pack without runtime side effects."""

import base64
import hashlib
import io
import json
import shutil
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction

from shared.exceptions import CMSError
from tests.cms.experiment_admission_fixtures import (
    FIXTURE,
    admit,
    write_experiment_content_manifest,
)
from tests.cms.experiment_admission_fixtures import (
    experiment_inputs as experiment_inputs,
)
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody

pytestmark = pytest.mark.django_db


def test_installed_pack_admission_retains_all_trials_and_reloads_without_compilation(experiment_inputs, monkeypatch):
    import socket

    from cms.models import ExperimentBatch, ExperimentEntry, ExperimentSnapshot
    from cms.services import load_experiment_batch
    from shared.raes import experiment_admission
    from shared.raes.experiment_dispatch_inputs import trial_scenario_bytes

    compiler = experiment_admission.compile_admitted_trial_plan
    original_sdl = (experiment_inputs[3] / "sdl/experiment-fixture.sdl.yaml").read_bytes()
    monkeypatch.setattr(
        socket.socket, "connect", lambda *args: pytest.fail("Admission must not open a network connection")
    )

    def reordered_compilation(request):
        result = compiler(request)
        assert result.plan is not None
        count = len(result.plan.entries)
        reordered = compiler(request, coordinate_partitions=(tuple(reversed(range(count))),))
        assert reordered.plan.model_dump(mode="json") == result.plan.model_dump(mode="json")
        return result

    monkeypatch.setattr(experiment_admission, "compile_admitted_trial_plan", reordered_compilation)

    batch = admit(experiment_inputs)
    actor, organization, _, root, _ = experiment_inputs
    assert batch.expected_trials == 64
    assert (root / "sdl/experiment-fixture.sdl.yaml").read_bytes() == original_sdl
    assert ExperimentBatch.objects.count() == 1
    assert ExperimentEntry.objects.count() == 64
    assert admit(experiment_inputs).id == batch.id
    raw = batch.inputs
    # #2922: the record keeps one digest per entry. Each entry's exact snapshot has its own row.
    assert "snapshots" not in raw
    assert ExperimentSnapshot.objects.count() == 64
    stored = dict(ExperimentSnapshot.objects.values_list("plan_entry_id", "snapshot_json"))
    assert set(stored) == set(raw["snapshot_digests"]) == set(raw["plan"]["entries"])
    for entry_id, snapshot in stored.items():
        assert trial_scenario_bytes(raw, entry_id, snapshot) == snapshot.encode()
        assert "sha256:" + hashlib.sha256(snapshot.encode()).hexdigest() == raw["snapshot_digests"][entry_id]
    entry_id = next(iter(stored))
    with pytest.raises(ValueError, match="admitted digest"):
        trial_scenario_bytes(raw, entry_id, stored[entry_id] + " ")
    with pytest.raises(ValueError, match="admitted digest"):
        trial_scenario_bytes(raw, entry_id, None)
    # Admission reads back each written snapshot and refuses one that differs from its recorded digest.
    written = [(entry_id, len(stored[entry_id].encode()))]
    changed = io.BytesIO(b" " * written[0][1])
    with pytest.raises(ValueError, match="recorded digest"):
        list(experiment_admission.read_snapshots(raw, changed, written))
    assert raw["capture_specs"]
    assert base64.b64decode(raw["artifacts"]["docs/protocol.md"]["base64"]) == (root / "docs/protocol.md").read_bytes()
    for name in ("brief-terse", "brief-rich"):
        key = f"prompts/{name}.txt"
        assert base64.b64decode(raw["artifacts"][key]["base64"]) == (root / key).read_bytes()
    assert raw["experiment"]["run_plan"]["allocation"]
    assert raw["plan"]["allocation"]["entry_order"]
    assert (
        raw["plan"]["stochastic_controls"]["allocation-control"]["executable_binding"]["root_entropy"]["value"]
        == "02" * 32
    )
    assert raw["plan"]["allocation"]["draws"]
    configurations = [entry["participant_configurations"] for entry in raw["plan"]["entries"].values()]
    assert "small-model" in json.dumps(configurations)
    assert "large-model" in json.dumps(configurations)
    assert "brief-terse" in json.dumps(configurations)
    assert "brief-rich" in json.dumps(configurations)
    assert raw["resource_limits"]["isolation_ceiling"] == 1
    assert raw["resource_limits"]["configured_concurrency_ceiling"] == 200
    shutil.rmtree(root)
    monkeypatch.setattr(
        "shared.raes.experiment_admission.compile_admitted_trial_plan",
        lambda *a, **kw: pytest.fail("Reload must not compile or allocate"),
    )
    assert load_experiment_batch(actor.credential, organization.uuid, batch.id).inputs == raw
    raw["plan"]["entries"].clear()
    assert load_experiment_batch(actor.credential, organization.uuid, batch.id).expected_trials == 64


@pytest.mark.parametrize("concurrency", [0, -1, True, 2, 201])
def test_concurrency_cannot_exceed_authority_or_isolation(experiment_inputs, concurrency):
    with pytest.raises(CMSError):
        admit(experiment_inputs, concurrency=concurrency)


def test_admission_binds_the_batch_to_the_selected_published_worker_profile(experiment_inputs):
    """#2924: the batch retains one exact worker host profile; an unpublished selection is refused."""
    from engine.models import WorkerPolicyRecord
    from shared.disposable_workers import WorkerPolicy

    policy = WorkerPolicy.model_validate(WorkerPolicyRecord.objects.get().configuration)
    batch = admit(experiment_inputs)
    assert batch.inputs["worker_profile"] == {"name": "default", "digest": policy.profiles["default"].digest}
    actor, organization, source, root, authority = experiment_inputs
    with pytest.raises(CMSError, match="worker profile"):
        admit((actor, organization, source, root, authority | {"worker_profile": "missing"}))


def test_omitted_documents_are_derived_from_the_bound_profile_and_claim_no_workflow_results(
    experiment_inputs, monkeypatch
):
    """#2928: BigRAE derives both documents from the profile; the fixture needs results that a worker lacks."""
    from raes_processor.manifest import reference_processor_manifest_payload

    from cms.models import ExperimentBatch
    from engine.models import WorkerPolicyRecord
    from shared.disposable_workers import WorkerPolicy
    from shared.raes import experiment_admission
    from shared.raes.worker_apparatus import worker_realization_envelope

    authority = experiment_inputs[-1]
    authority["capture_offers"] = authority.pop("backend")["capabilities"]["observation"]["capture_offers"]
    del authority["realization_envelope"]
    authority["processor"] = reference_processor_manifest_payload(compatible_backends=["shifter-disposable-worker"])
    compiler, refusals = experiment_admission.compile_admitted_trial_plan, []

    def recorded(request):
        result = compiler(request)
        refusals.append((request.realization_envelope, [item.code for item in result.diagnostics]))
        return result

    monkeypatch.setattr(experiment_admission, "compile_admitted_trial_plan", recorded)
    with pytest.raises(CMSError, match="verify installed inputs"):
        admit(experiment_inputs)
    profile = WorkerPolicy.model_validate(WorkerPolicyRecord.objects.get().configuration).profiles["default"]
    assert refusals == [(worker_realization_envelope(profile), ["trial-compiler.apparatus-capability-unproven"])]
    assert not ExperimentBatch.objects.exists()

    # A compiled plan is still refused: each fixture trial has two nodes, and a worker host is one.
    cleanup = authority["execution_authority"]["cleanup"]
    cleanup["clean_state"]["verification_probe_refs"] = ["absence:range"]
    cleanup["cleanup_obligations"]["destroy"] |= {"requirement": "best-effort", "verification_probe_refs": []}
    derive = experiment_admission.worker_backend_manifest
    results = ["workflow-result-envelope-v1", "evaluation-result-envelope-v1"]
    monkeypatch.setattr(
        experiment_admission,
        "worker_backend_manifest",
        lambda *args: (manifest := derive(*args)).model_copy(
            update={"supported_contract_versions": manifest.supported_contract_versions + results}
        ),
    )
    with pytest.raises(CMSError, match="verify installed inputs"):
        admit(experiment_inputs)
    assert refusals[-1][1] == []
    assert not ExperimentBatch.objects.exists()


@pytest.mark.parametrize("suffix", [".task.json", ".capture.json"])
def test_non_file_experiment_documents_are_ignored(experiment_inputs, suffix):
    (experiment_inputs[3] / "experiments" / f"ignored{suffix}").mkdir()
    assert admit(experiment_inputs).expected_trials == 64


def test_admission_requires_installation_and_tenant_authority(experiment_inputs):
    actor, organization, source, _, _authority = experiment_inputs
    actor.policy_accounts.discard(None)
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    actor.policy_accounts.add(None)
    actor.policy_accounts.discard(organization.account.uuid)
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    actor.policy_accounts.add(organization.account.uuid)
    source.organization_uuid = uuid4()
    source.save()
    with pytest.raises(CMSError):
        admit(experiment_inputs)


def test_admission_requires_approved_destination_and_rejects_changed_pack(experiment_inputs):
    from cms.models import TrialArchiveDestination

    _, organization, _, root, _ = experiment_inputs
    destination = TrialArchiveDestination.objects.get(organization_uuid=organization.uuid)
    destination.delete()
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    destination.organization_uuid = organization.uuid
    destination.save()
    (root / "experiments/crossed-design.exp.yaml").write_text("invalid: input")
    with pytest.raises(CMSError):
        admit(experiment_inputs)


def test_database_guards_protect_science_and_entry_identities(experiment_inputs):
    from cms.models import ExperimentBatch, ExperimentEntry

    batch = admit(experiment_inputs)
    for model, fields in (
        (ExperimentBatch, {"retained_json": "{}"}),
        (ExperimentBatch, {"organization_uuid": uuid4()}),
        (ExperimentEntry, {"run_id": "changed-run"}),
        (ExperimentEntry, {"plan_entry_id": "changed-entry"}),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.update(**fields)
    assert ExperimentBatch.objects.get(pk=batch.id).retained_json != "{}"


def test_claim_exclusion_worker_fencing_and_observation(experiment_inputs):
    from cms.services import claim_experiment_entry, observe_experiment_attempt, record_experiment_worker

    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    entry_id = next(iter(batch.inputs["plan"]["entries"]))
    claim = claim_experiment_entry(actor.credential, organization.uuid, batch.id, entry_id)
    assert claim is not None
    assert claim_experiment_entry(actor.credential, organization.uuid, batch.id, entry_id) is None
    other_id = next(key for key in batch.inputs["plan"]["entries"] if key != entry_id)
    assert claim_experiment_entry(actor.credential, organization.uuid, batch.id, other_id) is None
    record_experiment_worker(actor.credential, organization.uuid, claim.token, "worker-opaque")
    record_experiment_worker(actor.credential, organization.uuid, claim.token, "worker-opaque")
    with pytest.raises(CMSError):
        record_experiment_worker(actor.credential, organization.uuid, claim.token, "different-worker")
    with pytest.raises(CMSError):
        record_experiment_worker(actor.credential, organization.uuid, uuid4(), "worker-opaque")
    observe_experiment_attempt(actor.credential, organization.uuid, claim.token, "running")
    observe_experiment_attempt(actor.credential, organization.uuid, claim.token, "finished")
    with pytest.raises(CMSError):
        observe_experiment_attempt(actor.credential, organization.uuid, claim.token, "running")


def test_reload_and_operational_writes_refuse_foreign_ownership(experiment_inputs):
    from cms.services import (
        claim_experiment_entry,
        load_experiment_batch,
        observe_experiment_attempt,
        record_experiment_collection,
        record_experiment_worker,
    )

    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    from workspaces.models import Organization

    other_organization = Organization.objects.create(account=organization.account, name="Other research organization")
    entries = batch.inputs["plan"]["entries"]
    selected_id = next(reversed(entries))
    claim = claim_experiment_entry(actor.credential, organization.uuid, batch.id, selected_id)
    assert claim.run_id == entries[selected_id]["run_id"]
    assert load_experiment_batch(actor.credential, organization.uuid, batch.id).inputs["plan"] == batch.inputs["plan"]
    for action in (
        lambda: load_experiment_batch(actor.credential, other_organization.uuid, batch.id),
        lambda: record_experiment_worker(actor.credential, other_organization.uuid, claim.token, "worker-test"),
        lambda: observe_experiment_attempt(actor.credential, other_organization.uuid, claim.token),
        lambda: record_experiment_collection(actor.credential, organization.uuid, claim.token, uuid4()),
    ):
        with pytest.raises(CMSError):
            action()


@pytest.mark.parametrize("change", ["version", "owner", "credential", "capacity"])
def test_unsupported_authority_is_refused_without_partial_rows(experiment_inputs, change):
    from cms.models import ExperimentBatch, ExperimentEntry

    authority = experiment_inputs[-1]
    if change == "version":
        authority["participants"][0]["manifest"]["identity"]["version"] = "999.0.0"
    elif change == "owner":
        authority["participants"][0]["manifest"]["configuration_registry"]["owner"]["validator_id"] = "unknown"
    elif change == "credential":
        authority["backend"]["constraints"]["api_key"] = "must-never-be-retained"
    else:
        authority["max_concurrency"] = 0
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    assert not ExperimentBatch.objects.exists()
    assert not ExperimentEntry.objects.exists()


@pytest.mark.parametrize("revocation", ["credential", "installation", "organization"])
def test_revocation_during_compilation_rolls_back_admission(experiment_inputs, monkeypatch, revocation):
    from cms.models import ExperimentBatch, ExperimentEntry, ExperimentSnapshot
    from cms.services import _experiment_batches
    from management.models import PrincipalSession

    actor = experiment_inputs[0]
    original = _experiment_batches.compile_pack_experiment

    def compile_and_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        if revocation == "credential":
            PrincipalSession.objects.filter(credential_uuid=actor.credential.credential_uuid).delete()
        elif revocation == "installation":
            actor.policy_accounts.discard(None)
        else:
            actor.policy_accounts.discard(experiment_inputs[1].account.uuid)
        return result

    monkeypatch.setattr(_experiment_batches, "compile_pack_experiment", compile_and_revoke)
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    assert not ExperimentBatch.objects.exists()
    assert not ExperimentEntry.objects.exists()
    assert not ExperimentSnapshot.objects.exists()


def test_large_factorial_is_refused_without_reduction_or_partial_rows(experiment_inputs):
    import yaml

    from cms.models import ExperimentBatch, ExperimentEntry
    from cms.scenarios.pack_validation import pack_digest

    _, _, source, root, _ = experiment_inputs
    path = root / "experiments/crossed-design.exp.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["factorial_design"]["target_runs_per_condition"] = 10001
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    write_experiment_content_manifest(root)
    source.package_digest = pack_digest(root)
    source.save()
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    assert not ExperimentBatch.objects.exists()
    assert not ExperimentEntry.objects.exists()


def test_retained_byte_limit_refuses_atomic_admission(experiment_inputs, monkeypatch):
    from cms.models import ExperimentBatch, ExperimentEntry, ExperimentSnapshot

    monkeypatch.setattr("shared.raes.experiment_admission.MAX_RETAINED_BYTES", 1024)
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    assert not ExperimentBatch.objects.exists()
    assert not ExperimentEntry.objects.exists()
    assert not ExperimentSnapshot.objects.exists()


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_selected_prompt_content_must_be_present_and_match_its_owner_pin(experiment_inputs, change):
    from cms.models import ExperimentBatch
    from cms.scenarios.pack_validation import pack_digest

    _, _, source, root, _ = experiment_inputs
    prompt = root / "prompts/brief-terse.txt"
    if change == "missing":
        prompt.unlink()
    else:
        prompt.write_bytes(b"Changed but still syntactically valid prompt.\n")
    write_experiment_content_manifest(root)
    source.package_digest = pack_digest(root)
    source.save()
    with pytest.raises(CMSError):
        admit(experiment_inputs)
    assert not ExperimentBatch.objects.exists()


def test_object_installed_pack_uses_existing_bounded_storage_staging(experiment_inputs, settings, monkeypatch):
    import tarfile

    _, _, source, root, _ = experiment_inputs
    from tests.cms.test_tenant_pack_upload import PackStorage

    storage = PackStorage()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        output.add(root, arcname=root.name)
    settings.RAES_PACKAGE_BUCKET = "installed-pack-storage"
    settings.RAES_PACKAGE_PREFIX = "approved-packs"
    storage.objects[(settings.RAES_PACKAGE_BUCKET, "approved-packs/immutable.tar.gz")] = archive.getvalue()
    monkeypatch.setattr("cms.services._experiment_batches.get_object_storage", lambda: storage)
    source.source_kind = "object"
    source.package_ref = "immutable.tar.gz"
    source.save()
    batch = admit(experiment_inputs)
    assert batch.expected_trials == 64
    assert batch.inputs["source"]["package_digest"] == source.package_digest


def test_corrupt_retained_digest_is_refused_before_projection(experiment_inputs):
    from cms.models import ExperimentBatch
    from cms.services._experiment_batches import _project

    batch = admit(experiment_inputs)
    row = ExperimentBatch.objects.get(pk=batch.id)
    row.retained_digest = "0" * 64
    with pytest.raises(CMSError):
        _project(row)


def test_collection_joins_existing_custody_receipt_and_does_not_release_claim(experiment_inputs, tmp_path):

    from cms.models import ExperimentEntry
    from cms.services import (
        claim_experiment_entry,
        intake_trial_archive,
        observe_experiment_attempt,
        record_experiment_cleanup,
        record_experiment_collection,
        recover_experiment_claim,
    )
    from shared.raes.trial_archive import TrialArchiveIdentity, validate_trial_archive
    from tests.shared.raes.test_trial_archive import archive_bytes, encoded

    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    plan = batch.inputs["plan"]
    entry_id, entry = next(iter(plan["entries"].items()))
    assert recover_experiment_claim(actor.credential, organization.uuid, batch.id, entry_id) is None
    original = claim_experiment_entry(actor.credential, organization.uuid, batch.id, entry_id)
    token = original.token
    del original  # Simulate losing the claim response after its transaction commits.
    claim = recover_experiment_claim(actor.credential, organization.uuid, batch.id, entry_id)
    assert claim.token == token
    assert recover_experiment_claim(actor.credential, organization.uuid, batch.id, entry_id) == claim
    assert ExperimentEntry.objects.exclude(token=None).count() == 1
    assert claim_experiment_entry(actor.credential, organization.uuid, batch.id, entry_id) is None
    with pytest.raises(CMSError):
        recover_experiment_claim(actor.credential, uuid4(), batch.id, entry_id)
    with pytest.raises(CMSError):
        recover_experiment_claim(actor.credential, organization.uuid, batch.id, "unknown-entry")
    actor.policy_accounts.discard(organization.account.uuid)
    with pytest.raises(CMSError):
        recover_experiment_claim(actor.credential, organization.uuid, batch.id, entry_id)
    actor.policy_accounts.add(organization.account.uuid)
    identity = TrialArchiveIdentity(
        experiment_id=plan["input_refs"]["authoring_input_ref"]["ref_id"],
        plan_id=plan["plan_id"],
        entry_id=entry_id,
        run_id=entry["run_id"],
        attempt_id=str(claim.token),
        plan_digest=plan["plan_digest"],
        entry_digest=entry["entry_digest"],
        run_version="1",
    )

    def replace_records(original_plan, run):
        original_plan.clear()
        original_plan.update(plan)
        run["run_id"] = entry["run_id"]
        run["task_ref"] = plan["input_refs"]["task_ref"]
        run["stochastic_controls"] = list(plan["stochastic_controls"].values())
        run["stochastic_draws"] = entry["stochastic_draws"]
        run["realized_selections"] = [item["treatment"] for item in entry["selections"] if item.get("treatment")]
        accounting = run["execution_accounting"]
        accounting.update(
            plan_id=plan["plan_id"],
            plan_digest=plan["plan_digest"],
            plan_entry_id=entry_id,
            entry_digest=entry["entry_digest"],
            participant_configurations=entry["participant_configurations"],
        )
        accounting["attempts"][0]["execution_attempt_id"] = str(claim.token)

    captures = {f"specs/{key}.capture.json": encoded(value) for key, value in batch.inputs["capture_specs"].items()}
    captures["docs/protocol.md"] = (FIXTURE / "pack/docs/protocol.md").read_bytes()
    raw = archive_bytes(record_change=replace_records, extra=captures)
    original = tmp_path / "original.tar.gz"
    original.write_bytes(raw)
    validate_trial_archive(original, identity)
    receipt = intake_trial_archive(actor.credential, organization.uuid, identity, io.BytesIO(raw))
    assert receipt.expected == identity.as_record()
    record_experiment_collection(actor.credential, organization.uuid, claim.token, receipt.id)
    record_experiment_collection(actor.credential, organization.uuid, claim.token, receipt.id)
    assert ExperimentEntry.objects.get(token=claim.token).receipt_id == receipt.id
    other = next(key for key in plan["entries"] if key != entry_id)
    assert claim_experiment_entry(actor.credential, organization.uuid, batch.id, other) is None
    cleanup_id = entry["execution_controls"]["cleanup_plan_ref"]
    cleanup = plan["cleanup_plans"][cleanup_id]
    cleanup_receipt = {
        "schema_version": "trial-cleanup-receipt/v1",
        "receipt_id": "cleanup-observation",
        "cleanup_plan_ref": cleanup_id,
        "plan_entry_id": entry_id,
        "run_id": entry["run_id"],
        "execution_attempt_id": str(claim.token),
        "trial_outcome": "failed",
        "cleanup_status": "succeeded",
        "obligation_results": {
            key: {"obligation_id": key, "status": "succeeded", "evidence_refs": ["evidence:owner-verified-absence"]}
            for key in cleanup["cleanup_obligations"]
        },
    }
    with pytest.raises(CMSError):
        record_experiment_cleanup(actor.credential, organization.uuid, claim.token, cleanup_receipt)
    observe_experiment_attempt(actor.credential, organization.uuid, claim.token, "finished")
    with pytest.raises(CMSError):
        record_experiment_cleanup(
            actor.credential, organization.uuid, claim.token, {**cleanup_receipt, "execution_attempt_id": "stale"}
        )
    record_experiment_cleanup(actor.credential, organization.uuid, claim.token, cleanup_receipt)
    record_experiment_cleanup(actor.credential, organization.uuid, claim.token, cleanup_receipt)
    assert claim_experiment_entry(actor.credential, organization.uuid, batch.id, other) is not None


def test_admission_cli_emits_only_metadata_and_show_uses_retained_inputs(experiment_inputs, monkeypatch, tmp_path):
    actor, organization, source, root, authority = experiment_inputs
    monkeypatch.setattr("cms.management.commands.experiment_batch.credential_from_file", lambda path: actor.credential)
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(authority))
    output = io.StringIO()
    common = {"credential_file": "unused", "organization": organization.uuid, "stdout": output}
    call_command(
        "experiment_batch",
        "admit",
        scenario=source.scenario_id,
        experiment="fixture-crossed-design",
        apparatus_file=str(path),
        concurrency=1,
        **common,
    )
    result = json.loads(output.getvalue())
    assert result["expected_trials"] == 64
    assert "small-model" not in output.getvalue()
    assert "brief-rich" not in output.getvalue()
    shutil.rmtree(root)
    output.seek(0)
    output.truncate()
    call_command("experiment_batch", "show", batch=result["id"], **common)
    assert json.loads(output.getvalue()) == result
