"""Dispatch inputs derived from a retained experiment batch.

Dispatch stages each entry's trial unit, exact SDL, and admitted plan.
The admitted timeout bounds the attempt. Verified absence of the worker VM
provides cleanup evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from raes_contracts.canonical import canonical_json_bytes
from raes_contracts.contracts import TrialCleanupReceiptModel, validate_trial_cleanup_receipt
from raes_contracts.contracts.admitted_trial_plan_ingress import parse_admitted_trial_plan_json

from shared.raes.experiment_admission import retained_entry_snapshot


def trial_scenario_bytes(inputs: dict[str, Any], entry_id: str) -> bytes:
    """Return the canonical instantiated snapshot bytes of one entry, verified against its admitted digest."""
    return retained_entry_snapshot(inputs, entry_id)


def trial_unit_bytes(inputs: dict[str, Any], entry_id: str, scenario: bytes) -> bytes:
    """Return the staged trial unit: the admitted plan, the entry and its instantiated snapshot."""
    return canonical_json_bytes({"plan": inputs["plan"], "plan_entry_id": entry_id, "snapshot": json.loads(scenario)})


def trial_plan_bytes(inputs: dict[str, Any]) -> bytes:
    """Return the exact admitted plan bytes that dispatch stages for every entry."""
    return canonical_json_bytes(inputs["plan"])


def trial_scenario_sha256(inputs: dict[str, Any], entry_id: str) -> str:
    """Return the prefixed digest of one entry's instantiated snapshot."""
    if "snapshot_digests" in inputs:
        return str(inputs["snapshot_digests"][entry_id])
    return "sha256:" + hashlib.sha256(trial_scenario_bytes(inputs, entry_id)).hexdigest()


_OUTCOME_TRIGGERS = {
    "succeeded": "success",
    "failed": "failure",
    "cancelled": "cancellation",
    "timed-out": "timeout",
    "aborted": "abort",
}


def entry_attempt_timeout(inputs: dict[str, Any], entry_id: str) -> int:
    """Return the admitted attempt timeout of one retained entry."""
    plan = parse_admitted_trial_plan_json(trial_plan_bytes(inputs))
    return plan.entries[entry_id].execution_controls.attempt_timeout_seconds


def worker_absence_cleanup_receipt(
    inputs: dict[str, Any], entry_id: str, attempt_id: str, *, trial_outcome: str, evidence_ref: str
) -> dict[str, Any]:
    """Report the retained cleanup plan as met by verified absence of the trial's worker VM.

    The worker VM is the trial's only resource boundary, so its verified provider
    absence satisfies every obligation that the outcome triggers.
    """
    plan = parse_admitted_trial_plan_json(trial_plan_bytes(inputs))
    entry = plan.entries[entry_id]
    cleanup = plan.cleanup_plans[entry.execution_controls.cleanup_plan_ref]
    trigger = _OUTCOME_TRIGGERS[trial_outcome]
    results = {
        obligation_id: {
            "obligation_id": obligation_id,
            "status": "succeeded" if trigger in obligation.triggers else "not-triggered",
            "evidence_refs": [evidence_ref] if trigger in obligation.triggers else [],
            "residual_state_refs": [],
        }
        for obligation_id, obligation in cleanup.cleanup_obligations.items()
    }
    receipt = TrialCleanupReceiptModel.model_validate(
        {
            "receipt_id": f"worker-absence:{attempt_id}",
            "cleanup_plan_ref": cleanup.plan_id,
            "plan_entry_id": entry_id,
            "run_id": entry.run_id,
            "execution_attempt_id": attempt_id,
            "trial_outcome": trial_outcome,
            "cleanup_status": "succeeded",
            "obligation_results": results,
            "clean_state_claim": {
                # The destroyed worker leaves no residual state; a later trial gets a new worker.
                "disposition": "verified-clean",
                "boundary_refs": list(cleanup.clean_state.boundary_refs),
                "evidence_refs": [evidence_ref],
            },
        }
    )
    validate_trial_cleanup_receipt(cleanup, receipt)
    return receipt.model_dump(mode="json")
