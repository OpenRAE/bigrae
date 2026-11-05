"""Accept reference-only project capture in the existing result transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import GcpRangeProject, OperationInput, OperationResultDisposition, ProvisionerLaunchIntent
from shared.gcp_project_registration import GcpProjectRegistrationInput, GcpProjectRegistrationReceipt
from shared.operation_authority import credential_reference_from_record
from shared.operation_results import latest_step, step_follows

from ._gcp_project_operations import validate_project_operation
from ._gcp_project_registration import _audit_project, project_authority_fields, require_project_administrator
from ._operation_apply_admission import applied_steps, has_conflicting_sibling, has_earlier_pending_sibling

if TYPE_CHECKING:
    from typing import Any

    from engine.models import OperationResultInbox


def apply_project_registration_result(result: OperationResultInbox, payload: dict[str, Any]) -> tuple[str, str]:
    """Bind successful capture to the original scope, worker generation and storage root."""
    row = GcpRangeProject.objects.select_for_update().filter(provisioner_operation_id=result.operation_id).first()
    if row is None:
        return OperationResultDisposition.REJECTED_STALE, "Registered project operation changed"
    admission = _receipt_disposition(result)
    if admission is not None:
        return admission
    try:
        intent = ProvisionerLaunchIntent.objects.get(operation_id=result.operation_id)
        validate_project_operation(intent.payload, result.operation_id, receipt=True)
        current = require_project_administrator(credential_reference_from_record(intent))
        fields = project_authority_fields(current, row)
        if any(getattr(intent, name) != value for name, value in fields.items()):
            raise ValueError("Registered project authority changed")
        if result.result_kind == "TERMINAL_SUCCESS":
            original = GcpProjectRegistrationInput.model_validate(
                OperationInput.objects.get(operation_id=result.operation_id).envelope["payload"]
            )
            receipt = GcpProjectRegistrationReceipt.model_validate(payload)
            receipt.authorize(original, result.operation_id)
            row.baseline = receipt.baseline.model_dump(mode="json")
            row.project_number = receipt.project_number
            row.failure_code = ""
            row.status = "disabled" if row.status == "disabled" else "ready"
        else:
            row.failure_code = "capture-failed"
            row.status = "disabled" if row.status == "disabled" else "failed"
    except (ValueError, PermissionError):
        disposition = OperationResultDisposition.REJECTED_INVALID, "Registered project receipt unavailable"
    else:
        row.save(update_fields=["baseline", "project_number", "failure_code", "status", "updated_at"])
        _audit_project(row, current, "capture" if result.result_kind == "TERMINAL_SUCCESS" else "capture-failed")
        disposition = OperationResultDisposition.APPLIED, "Registered project capture applied"
    return disposition


def _receipt_disposition(result: OperationResultInbox) -> tuple[str, str] | None:
    """Preserve native sibling conflict and terminal-order fences under the project lock."""
    if has_earlier_pending_sibling(result):
        return "", ""
    if has_conflicting_sibling(result):
        return OperationResultDisposition.REJECTED_CONFLICT, "Registered project receipt conflict"
    previous = latest_step(result.resource, result.operation, applied_steps(result))
    return (
        None
        if step_follows(result.resource, result.operation, previous=previous, step=result.result_step)
        else (OperationResultDisposition.REJECTED_ORDERING, "Registered project result is out of order")
    )
