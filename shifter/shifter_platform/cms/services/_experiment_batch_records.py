"""Immutable projections for admitted batches and their operational attempts."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetainedExperimentBatch:
    """A fresh authorized copy; its scientific identities belong to RAES."""

    id: UUID
    inputs: dict[str, Any]

    @property
    def expected_trials(self) -> int:
        """Return the complete admitted entry count."""
        return len(self.inputs["plan"]["entries"])

    def summary(self) -> dict[str, Any]:
        """Expose identities and limits without scientific bodies."""
        return {
            "id": str(self.id),
            "plan_id": self.inputs["plan"]["plan_id"],
            "plan_digest": self.inputs["plan"]["plan_digest"],
            "expected_trials": self.expected_trials,
            "resource_limits": self.inputs["resource_limits"],
        }


@dataclass(frozen=True, slots=True)
class ExperimentClaim:
    """An exclusive initial attempt over an already allocated run."""

    token: UUID
    batch_id: UUID
    plan_entry_id: str
    run_id: str
    state: str
    worker_ref: str
    collection_receipt_id: UUID | None
    cleanup_recorded: bool
