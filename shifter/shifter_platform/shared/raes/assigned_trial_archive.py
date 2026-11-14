"""Intake and verification of an assigned trial's sealed archive (issue #2914).

The worker's archive carries the RAES trial outcome and the evidence that the
outcome references. BigRAE validates the archive's exact bytes and seal, then
gives the outcome to the RAES coordinator. As the coordinator's outcome
verifier, BigRAE checks that each evidence record belongs to the run and that
every byte it references is in the archive with its checksum and size. BigRAE
reads the archive; it cannot observe the worker guest, so in-guest facts rest
on the worker runtime's records.
"""

from __future__ import annotations

from pathlib import Path

from raes_contracts.assigned_trial import TrialOutcomeModel
from raes_contracts.trial_unit import TrialUnitRequest
from shifter_adapter_sdk.trial import TRIAL_OUTCOME_FILE, AssignedTrialSeal

from shared.raes.trial_archive import (
    MAX_ARCHIVE_BYTES,
    SEAL_NAME,
    TrialArchiveError,
    TrialArchiveIdentity,
    _json,
    _scan,
    safe_archive_path,
)
from shared.raes.trial_archive_records import verify_byte_references

Inventory = dict[str, tuple[int, str]]


def validate_assigned_trial_archive(path: Path, expected: TrialArchiveIdentity) -> tuple[TrialOutcomeModel, Inventory]:
    """Return the archived outcome and the exact member inventory, after the seal matches every byte."""
    if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise TrialArchiveError("Archive exceeds its compressed size bound")
    members, documents, _, _, _ = _scan(path, expected)
    seal = AssignedTrialSeal.model_validate(_json(documents[SEAL_NAME]))
    if (seal.run_id, seal.attempt_id) != (expected.run_id, expected.attempt_id):
        raise TrialArchiveError("The archive seal belongs to another attempt")
    declared = {safe_archive_path(item.path): (item.size_bytes, item.checksum.value) for item in seal.inventory}
    inventory = {name: identity for name, identity in members.items() if name != SEAL_NAME}
    if declared != inventory:
        raise TrialArchiveError("Archive inventory is incomplete or corrupt")
    checked, documents, _, _, _ = _scan(path, expected, dict.fromkeys(members, "binary") | _formats())
    if checked != members:
        raise TrialArchiveError("Archive bytes changed during validation")
    return TrialOutcomeModel.from_json(documents[TRIAL_OUTCOME_FILE]), inventory


def _formats() -> dict[str, str]:
    """Parse only the seal and the outcome as bounded JSON documents."""
    return {SEAL_NAME: "json", TRIAL_OUTCOME_FILE: "json"}


class ArchivedOutcomeVerifier:
    """BigRAE's RAES outcome verifier for one attempt, bound to that attempt's archive inventory."""

    def __init__(self, inventory: Inventory) -> None:
        self._inventory = dict(inventory)

    def verify_outcome(self, request: TrialUnitRequest, outcome: TrialOutcomeModel) -> None:
        """Raise unless every evidence record belongs to the run and its bytes are in the archive."""
        records = [record for fact in outcome.facts for record in fact.observation.evidence]
        if any(record.run_ref.ref_id != request.run_id for record in records):
            raise ValueError("Outcome evidence belongs to another run")
        verify_byte_references([record.model_dump(mode="json") for record in records], self._inventory, request.run_id)


__all__ = ["ArchivedOutcomeVerifier", "validate_assigned_trial_archive"]
