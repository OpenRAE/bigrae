"""Dispatch inputs derived from a retained experiment batch.

Dispatch stages each entry's admitted trial unit, bounds the attempt by its admitted
timeout, and reports cleanup as met by verified absence of the trial's worker VM.
"""

from __future__ import annotations

import hashlib
from typing import Any

from raes_contracts.canonical import canonical_json_bytes
from raes_contracts.contracts import TrialCleanupReceiptModel, validate_trial_cleanup_receipt
from raes_contracts.contracts.admitted_trial_plan_ingress import parse_admitted_trial_plan_json


def trial_scenario_bytes(inputs: dict[str, Any], entry_id: str) -> bytes:
    """Return the canonical instantiated snapshot bytes of one entry."""
    return canonical_json_bytes(inputs["snapshots"][entry_id])


def trial_unit_bytes(inputs: dict[str, Any], entry_id: str) -> bytes:
    """Return the staged trial unit: the admitted plan, the entry and its instantiated snapshot."""
    return canonical_json_bytes(
        {"plan": inputs["plan"], "plan_entry_id": entry_id, "snapshot": inputs["snapshots"][entry_id]}
    )


def trial_scenario_sha256(inputs: dict[str, Any], entry_id: str) -> str:
    """Return the prefixed digest of one entry's instantiated snapshot."""
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
    plan = parse_admitted_trial_plan_json(canonical_json_bytes(inputs["plan"]))
    return plan.entries[entry_id].execution_controls.attempt_timeout_seconds


def worker_absence_cleanup_receipt(
    inputs: dict[str, Any], entry_id: str, attempt_id: str, *, trial_outcome: str, evidence_ref: str
) -> dict[str, Any]:
    """Report the retained cleanup plan as met by verified absence of the trial's worker VM.

    The worker VM is the trial's only resource boundary, so its verified provider
    absence satisfies every obligation that the outcome triggers.
    """
    plan = parse_admitted_trial_plan_json(canonical_json_bytes(inputs["plan"]))
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
                "disposition": "fresh-range-required",
                "boundary_refs": list(cleanup.clean_state.boundary_refs),
                "evidence_refs": [evidence_ref],
            },
        }
    )
    validate_trial_cleanup_receipt(cleanup, receipt)
    return receipt.model_dump(mode="json")
