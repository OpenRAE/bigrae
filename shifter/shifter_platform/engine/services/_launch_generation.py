"""Generation and immutable-input checks for persisted provisioner launch intents.

Launch admission, dispatch, and failure handling call these checks before an
effect. They fence a launch intent to its current domain-operation generation.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import Model, QuerySet

from engine.launch_target import lock_provisioner_target
from engine.models import Instance, OperationInput, ProvisionerLaunchIntent, Range, Request
from engine.services._gcp_project_operations import validate_project_operation
from engine.services._launch_authority import assert_input_authority_binding, assert_launch_authority_binding
from engine.services._operation_inputs import operation_input_payload
from engine.services._vpn_profile_operations import validate_vpn_operation
from engine.services._worker_trials import validate_worker_trial_operation
from engine.warm_activation_authz import authorize_warm_activation
from shared.operation_envelope import canonical_payload_digest

_OPERATION_AUTHORITY_UNAVAILABLE = "Operation authority unavailable"


def _lock_for_generation[ModelT: Model](
    queryset: QuerySet[ModelT], expected_operation_id: UUID | str | None
) -> QuerySet[ModelT]:
    """Lock a domain projection when validating a persisted operation generation."""
    return queryset.select_for_update() if expected_operation_id is not None else queryset


def _require_current_generation(row: Range | Instance, expected_operation_id: UUID | str | None) -> None:
    """Reject an intent that belongs to a superseded domain-operation generation."""
    if expected_operation_id is not None and row.provisioner_operation_id != UUID(str(expected_operation_id)):
        raise ValueError("launch intent operation generation is no longer current")
    principal_owned = (isinstance(row, Range) and row.owner_principal_uuid is not None) or (
        isinstance(row, Instance) and row.request is not None and row.request.owner_principal_uuid is not None
    )
    if principal_owned and expected_operation_id is not None:
        intent = ProvisionerLaunchIntent.objects.filter(operation_id=expected_operation_id).first()
        if intent is None:
            raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
        assert_launch_authority_binding(intent, row)


def _authorize_legacy_range(
    payload: dict[str, object],
    target: Range | Instance | None,
    expected_operation_id: UUID | str | None,
) -> None:
    """Authorize a legacy range-id/user-id payload."""
    range_rows = _lock_for_generation(Range.objects.all(), expected_operation_id)
    row = target if isinstance(target, Range) else range_rows.filter(pk=int(str(payload.get("range_id")))).first()
    if row is None or row.user_id != payload.get("user_id"):
        raise ValueError("legacy launch intent does not match an owned range")
    _require_current_generation(row, expected_operation_id)
    allowed_states = {
        "provision": {Range.Status.PENDING, Range.Status.PROVISIONING},
        "destroy": {Range.Status.DESTROYING},
    }
    if row.status not in allowed_states[str(payload.get("operation"))]:
        raise ValueError("range state does not authorize the requested operation")


def _authorize_request_range(
    payload: dict[str, object],
    request: Request,
    target: Range | Instance | None,
    expected_operation_id: UUID | str | None,
) -> None:
    """Authorize a request-based Range or RAES Range payload."""
    range_rows = _lock_for_generation(Range.objects.all(), expected_operation_id)
    row = target if isinstance(target, Range) else range_rows.filter(request=request).first()
    if row is None:
        raise ValueError("launch intent request has no range")
    _require_current_generation(row, expected_operation_id)
    operation = str(payload.get("operation"))
    if operation == "activate":
        # Warm activation (#28) authority lives on its own seam; the claimed warm
        # generation on a quarantined range is the authority, not a READY range.

        authorize_warm_activation(request, row)
        return
    allowed_states = {
        "provision": {Range.Status.PENDING, Range.Status.PROVISIONING},
        "destroy": {Range.Status.DESTROYING},
        "pause": {Range.Status.PAUSING},
        "resume": {Range.Status.RESUMING},
    }
    if row.status not in allowed_states[operation]:
        raise ValueError("range state does not authorize the requested operation")


def _authorize_request_ngfw(
    payload: dict[str, object],
    request: Request,
    target: Range | Instance | None,
    expected_operation_id: UUID | str | None,
) -> None:
    """Authorize a request-based NGFW payload."""
    ngfw_rows = _lock_for_generation(Instance.objects.all(), expected_operation_id)
    row = target if isinstance(target, Instance) else ngfw_rows.filter(request=request, role=Instance.Role.NGFW).first()
    if row is None:
        raise ValueError("launch intent request has no NGFW instance")
    _require_current_generation(row, expected_operation_id)
    allowed_states = {
        "provision": {"pending", "provisioning"},
        "deprovision": {"ready", "paused", "failed", "destroying"},
        "start": {"paused", "failed"},
        "stop": {"ready"},
    }
    if row.status not in allowed_states[str(payload.get("operation"))]:
        raise ValueError("NGFW state does not authorize the requested operation")


def assert_provisioner_input_matches(payload: dict[str, object], operation_id: UUID) -> None:
    """Fence immutable input at effect admission, independently of failure evidence."""
    if payload.get("resource") == "range-project":
        validate_project_operation(payload, operation_id)
        return
    if payload.get("resource") == "vpn-profile":
        validate_vpn_operation(payload, operation_id)
        return
    if payload.get("resource") == "worker-trial":
        validate_worker_trial_operation(payload, operation_id)
        return
    intent = ProvisionerLaunchIntent.objects.filter(operation_id=operation_id).first()
    if intent is not None and intent.authority_kind:
        _assert_stored_intent_matches(payload, operation_id)


def _validate_native_generation(payload: dict[str, object], expected_operation_id: UUID | str | None) -> bool:
    """Fence a project, VPN profile or worker trial operation; return False for other resources."""
    resource = payload.get("resource")
    if resource == "range-project":
        validate_project_operation(payload, expected_operation_id)
    elif resource == "vpn-profile":
        validate_vpn_operation(payload, expected_operation_id)
    elif resource == "worker-trial":
        validate_worker_trial_operation(payload, expected_operation_id)
    else:
        return False
    return True


def validate_provisioner_generation(
    payload: dict[str, object],
    *,
    target: Range | Instance | None = None,
    expected_operation_id: UUID | str | None = None,
) -> None:
    """Fence domain facts only; callers admitting effects first authorize policy."""
    if _validate_native_generation(payload, expected_operation_id):
        return
    if "request_id" not in payload:
        _authorize_legacy_range(payload, target, expected_operation_id)
        return
    request = Request.objects.filter(request_id=UUID(str(payload["request_id"]))).first()
    if request is None:
        raise ValueError("launch intent request does not exist")
    if payload.get("resource") in {"range", "raes-range"}:
        _authorize_request_range(payload, request, target, expected_operation_id)
    else:
        _authorize_request_ngfw(payload, request, target, expected_operation_id)


def _lock_operation_target(payload: dict[str, object]) -> Range | Instance:
    """Lock and return the domain row that owns an operation generation."""
    target = lock_provisioner_target(payload)
    if not isinstance(target, (Range, Instance)):
        raise ValueError("launch intent has no operation target")
    return target


def _assert_stored_intent_matches(payload: dict[str, object], operation_id: UUID) -> None:
    """Reject a re-enqueue whose composed intent differs from the immutable input.

    The ``OperationInput`` is immutable per operation generation, but immutability
    alone does not prove replay equivalence: reusing the stored input for a
    re-enqueue whose compiled plan or bindings have since changed would silently
    launch stale intent. Compose the current intent and compare its canonical
    digest to the stored one, failing closed on a mismatch (ADR-063-R2). No stored
    input (a legacy range) means there is nothing to compare.
    """
    intent = ProvisionerLaunchIntent.objects.filter(operation_id=operation_id).first()
    stored = OperationInput.objects.filter(operation_id=operation_id).first()
    if stored is None:
        if intent is not None and intent.authority_kind:
            raise ValueError(_OPERATION_AUTHORITY_UNAVAILABLE)
        return

    if intent is not None:
        assert_input_authority_binding(stored, intent)
    target = _lock_operation_target(payload)
    request: Request | None = getattr(target, "request", None)
    if request is None:
        return
    current = operation_input_payload(target, str(payload["resource"]), request, operation=str(payload["operation"]))
    stored_payload = (stored.envelope or {}).get("payload") or {}
    if canonical_payload_digest(current) != canonical_payload_digest(stored_payload):
        raise ValueError("re-enqueue intent does not match the stored immutable operation intent")
