"""Bind a LilRAE trial seal to the expected attempt and its admitted trial SDL.

The trial record has no RAES plan. The expected scenario digest is the digest
of the retained entry's trial SDL, so it binds the admitted plan entry.
"""

from __future__ import annotations

from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity, _json
from shared.schemas._raes_validation import JsonObject

TRIAL_RECORD_CONTRACT = "lilrae-trial-record/v1"
TRIAL_RECORD_NAME = "trial/record.json"


def _trial_record_matches(
    record: JsonObject, marker: JsonObject, expected: TrialArchiveIdentity, trace_attempts: set[str]
) -> bool:
    """Return True when the record, the seal and the traces name only the expected attempt."""
    return bool(
        expected.scenario_sha256
        and record.get("schema_version") == TRIAL_RECORD_CONTRACT
        and record.get("run_id") == expected.run_id
        and record.get("attempt_id") == expected.attempt_id
        and record.get("scenario_sha256") == expected.scenario_sha256
        and marker.get("run_id") == expected.run_id
        and marker.get("run_version") == expected.run_version
        and trace_attempts <= {expected.attempt_id}
    )


def validate_trial_record(
    documents: dict[str, bytes], marker: JsonObject, expected: TrialArchiveIdentity, trace_attempts: set[str]
) -> tuple[str, str, bool, int, None]:
    """Return the sealed outcome of a trial record that binds the expected attempt."""
    if not _trial_record_matches(_json(documents[TRIAL_RECORD_NAME]), marker, expected, trace_attempts):
        raise TrialArchiveError("Trial record identity differs from the expected attempt")
    completeness = marker.get("completeness")
    limitations = completeness.get("limitations") if isinstance(completeness, dict) else None
    if not isinstance(limitations, list):
        raise TrialArchiveError("Trial seal limitations are invalid")
    return str(marker["run_status"]), str(marker["outcome_status"]), not limitations, len(limitations), None
