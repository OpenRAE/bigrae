"""Compile one RAES replacement trial from a retained experiment batch.

The experiment's ``replacement_policy`` authorizes the replacement. RAES
compiles the child plan from the original compilation request, the original
plan, the qualifying failed run, its cleanup receipt and the slot's complete
replacement history. This module adds no effects; the caller persists the
result before dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from raes.canonical import canonical_instantiated_sdl_bytes
from raes_contracts.canonical import canonical_json_bytes
from raes_contracts.contracts import ExperimentRunModel, TrialCleanupReceiptModel
from raes_contracts.contracts.admitted_trial_plan_ingress import parse_admitted_trial_plan_json
from raes_contracts.errors import RaesError
from raes_processor.trial_compiler.replacement import TrialReplacementResult, compile_replacement_trial
from raes_processor.trial_realization import instantiate_admitted_trial_entry

from shared.raes.experiment_admission import ExperimentAuthority, _context, _select_experiment
from shared.raes.participant_owner_replay import OwnerValidation


def replacement_allowed(inputs: dict[str, Any], run_status: str, ordinal: int) -> bool:
    """Return whether the admitted policy authorizes replacement number ``ordinal`` for this run status."""
    policy = inputs["plan"].get("replacement_policy") or {}
    return run_status in policy.get("replace_on", []) and ordinal <= policy.get("max_replacements", 0)


def _history(item: dict[str, Any]) -> TrialReplacementResult:
    """Restore one committed replacement decision of the slot."""
    return TrialReplacementResult(
        plan=parse_admitted_trial_plan_json(canonical_json_bytes(item["plan"])),
        superseded_run=ExperimentRunModel.model_validate(item["superseded_run"]),
        parent_run=ExperimentRunModel.model_validate(item["parent_run"]),
        cleanup_receipts=tuple(TrialCleanupReceiptModel.model_validate(r) for r in item["cleanup_receipts"]),
    )


def compile_experiment_replacement(
    root: Path,
    inputs: dict[str, Any],
    *,
    root_entry_id: str,
    previous: list[dict[str, Any]],
    failed_run: dict[str, Any],
    cleanup_receipt: dict[str, Any],
    owner_validation: OwnerValidation,
) -> dict[str, Any]:
    """Compile and realize the next replacement for one slot; raise ``ValueError`` on refusal.

    RAES reports its own refusals as ``RaesError``. Callers outside ``shared.raes``
    handle a refusal as ``ValueError``, so this boundary converts the error.
    """
    try:
        return _compile(
            root,
            inputs,
            root_entry_id=root_entry_id,
            previous=previous,
            failed_run=failed_run,
            cleanup_receipt=cleanup_receipt,
            owner_validation=owner_validation,
        )
    except RaesError as exc:
        raise ValueError(str(exc)) from exc


def _compile(
    root: Path,
    inputs: dict[str, Any],
    *,
    root_entry_id: str,
    previous: list[dict[str, Any]],
    failed_run: dict[str, Any],
    cleanup_receipt: dict[str, Any],
    owner_validation: OwnerValidation,
) -> dict[str, Any]:
    """Compile and realize the next replacement for one slot."""
    experiment = _select_experiment(root, inputs["experiment"]["spec_id"], inputs["experiment"]["spec_version"])
    authority = ExperimentAuthority.model_validate(inputs["authority"])
    request = experiment.compilation_request(**_context(experiment, authority, owner_validation))
    result = compile_replacement_trial(
        request,
        original_plan=parse_admitted_trial_plan_json(canonical_json_bytes(inputs["plan"])),
        root_entry_id=root_entry_id,
        previous_allocations=[_history(item) for item in previous],
        failed_run=ExperimentRunModel.model_validate(failed_run),
        cleanup_receipts=[TrialCleanupReceiptModel.model_validate(cleanup_receipt)],
    )
    if result.plan is None or result.superseded_run is None or result.parent_run is None:
        codes = ",".join(sorted({item.code for item in result.diagnostics})) or "unknown"
        raise ValueError(f"Replacement refused: {codes}")
    entry_id = next(iter(result.plan.entries))
    selected = instantiate_admitted_trial_entry(plan=result.plan, plan_entry_id=entry_id, family=experiment.family)
    return {
        "root_entry_id": root_entry_id,
        "plan": result.plan.model_dump(mode="json"),
        "snapshot": json.loads(canonical_instantiated_sdl_bytes(selected)),
        "superseded_run": result.superseded_run.model_dump(mode="json"),
        "parent_run": result.parent_run.model_dump(mode="json"),
        "cleanup_receipts": [r.model_dump(mode="json") for r in result.cleanup_receipts],
    }
