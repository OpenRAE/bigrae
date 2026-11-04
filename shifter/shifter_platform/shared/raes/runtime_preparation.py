"""Validate adapter selections with the original public RAES authority owners."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import TypeAdapter
from raes_contracts.bounded_domains import DomainDescriptor, scalar_in_domain
from raes_contracts.canonical import JsonValue
from raes_contracts.realization_structure import (
    RealizationConstraintDocument,
    RealizationRelationStatus,
    RealizationStructure,
    evaluate_realization_constraint,
    structure_matches,
)
from raes_contracts.runtime_value_limits import PLAN_AUTHORITY_LIMITS
from raes_processor.semantics.realization_concerns import project_realization_concern
from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

from shared.gcp_runtime_plan import selected_secret_payloads
from shared.runtime_plugin_binding import RuntimePluginPin
from shared.runtime_plugin_preparation import apply_prepared_values, governing_authorities, pointer_value

_INVALID = "Preparation does not conform to the original admitted plan"
_DOMAIN = TypeAdapter(DomainDescriptor)
_STRUCTURE = TypeAdapter(RealizationStructure)


def validate_runtime_preparation(plan: dict[str, Any], result: RuntimePlan, pin: RuntimePluginPin) -> dict[str, Any]:
    """Accept only selections within every original constraint before any effect."""
    try:
        candidate = apply_prepared_values(plan, result, pin.manifest.provisioning_concerns)
        _validate_all_authorities(plan, candidate, result)
        _validate_guest_identity(plan, candidate, pin)
        selected_secret_payloads(plan, result, pin.manifest.provisioning_concerns)
        return candidate
    except Exception:  # noqa: BLE001  # constraint and value diagnostics may contain private supplied material
        raise ValueError(_INVALID) from None


def _validate_all_authorities(plan: dict[str, Any], candidate: dict[str, Any], result: RuntimePlan) -> None:
    """Evaluate each whole overlapping authority once, after all selections."""
    seen = set()
    for edit in result.provisioning_values:
        for row in governing_authorities(plan, edit):
            identity = (edit.address, canonical_digest(row))
            if identity not in seen:
                _validate_authority(
                    row, plan["resources"][edit.address]["payload"], candidate["resources"][edit.address]["payload"]
                )
                seen.add(identity)


def _validate_guest_identity(plan: dict[str, Any], candidate: dict[str, Any], pin: RuntimePluginPin) -> None:
    """Already-queued guest phases keep exactly their admitted OS and node count."""
    pin.bindings.validate_plan(candidate)
    for address in pin.bindings.targets.values():
        if plan["resources"][address]["payload"].get("os_family") != candidate["resources"][address]["payload"].get(
            "os_family"
        ):
            raise ValueError(_INVALID)


def _validate_authority(row: dict[str, Any], original: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Evaluate whole concern values so a leaf edit cannot bypass parent constraints."""
    before = pointer_value(original, row["payload_pointer"])
    after = pointer_value(candidate, row["payload_pointer"])
    if canonical_digest(before) == canonical_digest(after):
        return
    if row.get("mode") not in {"open", "constrained"}:
        raise ValueError(_INVALID)
    document, structure, bounds = row.get("constraint_document"), row.get("structure"), row.get("bounds", [])
    if document is not None and structure is not None:
        raise ValueError(_INVALID)
    if row["mode"] == "constrained" and not bounds and document is None:
        raise ValueError(_INVALID)
    _validate_structure(row, before, after)
    _validate_bounds(bounds, after)


def _validate_bounds(bounds: list[dict[str, Any]], after: object) -> None:
    """Require every typed bound and refuse unsupported identity-relative selection."""
    for bound in bounds:
        if bound.get("identity_digest") is not None:
            raise ValueError(_INVALID)
        selected = pointer_value(after, bound["value_pointer"])
        if not scalar_in_domain(selected, _DOMAIN.validate_python(bound["domain"])):
            raise ValueError(_INVALID)


def _validate_structure(row: dict[str, Any], before: object, after: object) -> None:
    """Use current recursive and legacy contracts through their public owner only."""
    if row.get("constraint_document") is not None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", row.get("constraint_binding", "")) is None:
            raise ValueError(_INVALID)
        document = RealizationConstraintDocument.model_validate(row["constraint_document"])
        projected = project_realization_concern(row["requirement_kind"], after, recursive=True)
        relation = evaluate_realization_constraint(document, projected, limits=PLAN_AUTHORITY_LIMITS)
        if relation.status is not RealizationRelationStatus.CONFORMANT:
            raise ValueError(_INVALID)
    elif row.get("constraint_binding") is not None:
        raise ValueError(_INVALID)
    if row.get("structure") is not None:
        projected_before = project_realization_concern(row["requirement_kind"], before)
        projected_after = project_realization_concern(row["requirement_kind"], after)
        if not structure_matches(
            _STRUCTURE.validate_python(row["structure"]),
            cast(JsonValue, projected_before),
            cast(JsonValue, projected_after),
            observed=False,
        ):
            raise ValueError(_INVALID)
