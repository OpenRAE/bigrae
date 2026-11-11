"""Validate a trial archive for experiment dispatch: containment, sealed bytes and the run record.

Dispatch needs only the run's status to decide cleanup and replacement. This
validator keeps the archive containment and byte-integrity checks, and reads no
record other than the run record.
"""

from __future__ import annotations

from pathlib import Path

from raes_contracts.contracts import ExperimentRunModel

from shared.raes.trial_archive import (
    LILRAE_SEAL,
    MANIFEST_NAME,
    MAX_ARCHIVE_BYTES,
    SEAL_NAME,
    TrialArchiveError,
    TrialArchiveIdentity,
    VerifiedTrialArchive,
    _inventory,
    _json,
    _scan,
)
from shared.raes.trial_archive_paths import RECORD_ERRORS


def validate_trial_run_record(path: Path, expected: TrialArchiveIdentity) -> VerifiedTrialArchive:
    """Verify containment and sealed bytes, then project the run record only."""
    try:
        if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
            raise TrialArchiveError("Archive exceeds its compressed size bound")
        members, documents, _, _, _ = _scan(path, expected)
        marker = _json(documents[SEAL_NAME])
        _inventory(marker, members, documents)
        run_digest = "sha256:" + members[MANIFEST_NAME][1]
        if marker.get("run_record_digest") != run_digest:
            raise TrialArchiveError("Sealed manifest digest does not match")
        if marker.get("schema_version") == LILRAE_SEAL:
            # A LilRAE seal states the run's status itself; its manifest is not a RAES run record.
            run_id, run_status, outcome_status = marker["run_id"], marker["run_status"], marker["outcome_status"]
        else:
            run = ExperimentRunModel.model_validate(_json(documents[MANIFEST_NAME]))
            run_id, run_status, outcome_status = run.run_id, run.run_status, run.outcome_status
        if run_id != expected.run_id or not isinstance(run_status, str) or not isinstance(outcome_status, str):
            raise TrialArchiveError("Archive run differs from the expected run")
        return VerifiedTrialArchive(len(members), run_digest, run_status, outcome_status, False, 0)
    except TrialArchiveError:
        raise
    except RECORD_ERRORS:
        raise TrialArchiveError("Archive structure or run record validation failed") from None
