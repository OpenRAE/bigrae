"""#2914: BigRAE validates an assigned trial's archive and verifies its outcome evidence bytes."""

import hashlib
import io
import json
import tarfile
from importlib.resources import files
from types import SimpleNamespace

import pytest
from raes_contracts.assigned_trial import TrialOutcomeModel

from shared.raes.assigned_trial_archive import ArchivedOutcomeVerifier, validate_assigned_trial_archive
from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity

RUN, ATTEMPT = "run-1", "attempt-1"
EXPECTED = TrialArchiveIdentity(
    experiment_id="experiment-1",
    plan_id="plan-1",
    entry_id="entry-1",
    run_id=RUN,
    attempt_id=ATTEMPT,
    plan_digest="sha256:" + "1" * 64,
    entry_digest="sha256:" + "2" * 64,
    run_version="1",
)
FIXTURES = files("raes_contracts") / "_corpus/fixtures"


def _outcome(evidence_bytes, run=RUN):
    """The reference outcome plus a configuration fact whose evidence names archived bytes."""
    record = json.loads((FIXTURES / "experiment-core/experiment-evidence-record-v1/valid/reference.json").read_text())
    record["run_ref"]["ref_id"] = run
    record["raw_content"]["content_uri"] = "evidence/history.json"
    record["raw_content"]["content_checksum"]["value"] = hashlib.sha256(evidence_bytes).hexdigest()
    outcome = json.loads((FIXTURES / "control-plane/trial-outcome-v1/valid/reference.json").read_text())
    fact = {
        "observation": {"kind": "configuration", "configurations": [], "evidence": [record]},
        "observed_at": "2026-11-14T00:00:00Z",
    }
    return TrialOutcomeModel.model_validate(outcome | {"facts": [fact]})


def _archive(path, members, seal_changes=None):
    inventory = [
        {
            "path": name,
            "size_bytes": len(data),
            "checksum": {"value": hashlib.sha256(data).hexdigest()},
            "media_type": "application/json",
            "role": "evidence",
        }
        for name, data in members.items()
    ]
    seal = {
        "schema_version": "bigrae.assigned-trial-seal/v1",
        "run_id": RUN,
        "attempt_id": ATTEMPT,
        "outcome_digest": "sha256:" + hashlib.sha256(members["outcome.json"]).hexdigest(),
        "inventory": inventory,
    } | (seal_changes or {})
    with tarfile.open(path, "w:gz") as output:
        for name, data in {**members, "seal.json": json.dumps(seal).encode()}.items():
            info = tarfile.TarInfo(f"{RUN}/{name}")
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))
    return path


def test_the_outcome_and_its_evidence_bytes_are_verified(tmp_path):
    evidence = b'{"observed": true}'
    outcome = _outcome(evidence)
    members = {"outcome.json": outcome.model_dump_json().encode(), "evidence/history.json": evidence}
    archived, inventory = validate_assigned_trial_archive(_archive(tmp_path / "a.tar.gz", members), EXPECTED)
    assert archived == outcome and set(inventory) == set(members)
    ArchivedOutcomeVerifier(inventory).verify_outcome(SimpleNamespace(run_id=RUN), archived)
    with pytest.raises(ValueError, match="another run"):
        ArchivedOutcomeVerifier(inventory).verify_outcome(SimpleNamespace(run_id=RUN), _outcome(evidence, run="other"))
    with pytest.raises(TrialArchiveError, match="missing or corrupt"):
        ArchivedOutcomeVerifier(inventory).verify_outcome(SimpleNamespace(run_id=RUN), _outcome(b"other bytes"))


def test_a_seal_that_does_not_match_the_bytes_or_the_attempt_is_refused(tmp_path):
    evidence = b'{"observed": true}'
    members = {"outcome.json": _outcome(evidence).model_dump_json().encode(), "evidence/history.json": evidence}
    path = _archive(tmp_path / "a.tar.gz", members, {"attempt_id": "attempt-2"})
    with pytest.raises(TrialArchiveError, match="another attempt"):
        validate_assigned_trial_archive(path, EXPECTED)
    sealed = members | {"evidence/extra.json": b"{}"}
    path = _archive(tmp_path / "b.tar.gz", sealed)
    with tarfile.open(path) as archive:
        kept = {member.name: archive.extractfile(member).read() for member in archive if member.isfile()}
    with tarfile.open(path, "w:gz") as output:
        for name, data in kept.items():
            if not name.endswith("extra.json"):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                output.addfile(info, io.BytesIO(data))
    with pytest.raises(TrialArchiveError, match="incomplete or corrupt"):
        validate_assigned_trial_archive(path, EXPECTED)
