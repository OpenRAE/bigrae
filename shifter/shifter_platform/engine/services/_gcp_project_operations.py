"""Reference-only native baseline capture, generation and initiating-proof fences."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from engine.models import GcpRangeProject, InterruptState, OperationInput, ProvisionerLaunchIntent
from shared.credentials import CredentialContext
from shared.gcp_project_registration import GcpProjectRegistrationInput
from shared.operation_authority import credential_reference_from_record
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest

_UNAVAILABLE = "Registered project operation is unavailable"


def queue_project_registration(
    row: GcpRangeProject,
    current: CredentialContext,
    original: GcpProjectRegistrationInput,
    *,
    operation: str = "register",
) -> None:
    """Commit input, original authority and workload identity in the registration transaction."""
    from engine.ecs._workload import provisioner_workload
    from engine.launch_intents import command_from_payload

    from ._gcp_project_registration import project_authority_fields
    from ._launch_authority import authority_envelope_fields

    if operation not in {"register", "verify"} or (operation == "verify") != (original.baseline is not None):
        raise ValueError(_UNAVAILABLE)
    if not transaction.get_connection().in_atomic_block:
        raise ValueError(_UNAVAILABLE)
    operation_id, intent_id = uuid4(), uuid4()
    payload = {"version": 1, "resource": "range-project", "operation": operation, "request_id": str(row.pk)}
    workload = provisioner_workload(
        command_from_payload({**payload, "operation_id": str(operation_id)}), str(intent_id)
    )
    intent = ProvisionerLaunchIntent.objects.create(
        operation_id=operation_id,
        intent_id=intent_id,
        idempotency_key=sha256(f"range-project:{row.pk}:{operation_id}".encode()).hexdigest(),
        payload=payload,
        task_ref=f"{workload['namespace']}/{workload['job_name']}",
        next_attempt_at=timezone.now(),
        executing_workload=workload,
        **project_authority_fields(current, row),
    )
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=row.pk,
        resource="range-project",
        operation=operation,
        payload=original.model_dump(mode="json"),
        **authority_envelope_fields(intent),
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=row.pk,
        resource="range-project",
        operation=operation,
        contract_version=envelope["contract_version"],
        envelope=envelope,
    )
    row.provisioner_operation_id, row.provisioner_operation = operation_id, operation
    row.status, row.failure_code = "pending", ""
    row.save(
        update_fields=["provisioner_operation_id", "provisioner_operation", "status", "failure_code", "updated_at"]
    )


def validate_project_operation(
    payload: dict[str, object], operation_id: UUID | str | None, *, receipt: bool = False
) -> GcpRangeProject:
    """Require the exact original immutable input, target and current native generation."""
    from ._launch_authority import assert_input_authority_binding

    if operation_id is None:
        raise ValueError(_UNAVAILABLE)
    row = GcpRangeProject.objects.get(pk=UUID(str(payload["request_id"])))
    expected = {
        "version": 1,
        "resource": "range-project",
        "operation": row.provisioner_operation,
        "request_id": str(row.pk),
    }
    if (
        payload != expected
        or row.provisioner_operation_id != UUID(str(operation_id))
        or row.provisioner_operation not in {"register", "verify"}
    ):
        raise ValueError(_UNAVAILABLE)
    if row.status not in ({"pending", "disabled"} if receipt else {"pending"}):
        raise ValueError(_UNAVAILABLE)
    intent = ProvisionerLaunchIntent.objects.get(operation_id=operation_id)
    stored = OperationInput.objects.get(operation_id=operation_id)
    assert_input_authority_binding(stored, intent)
    original = _validate_capture_input(row, intent, stored, expected)
    _validate_capture_authority(row, intent, stored, original)
    return row


def _validate_capture_input(
    row: GcpRangeProject, intent: ProvisionerLaunchIntent, stored: OperationInput, expected: dict[str, object]
) -> GcpProjectRegistrationInput:
    """Keep original baseline, scope and interrupt state tied to this capture generation."""
    original = GcpProjectRegistrationInput.model_validate(stored.envelope["payload"])
    if (row.provisioner_operation == "verify") != (original.baseline is not None):
        raise ValueError(_UNAVAILABLE)
    if original.baseline is not None and original.baseline.model_dump(mode="json") != row.baseline:
        raise ValueError(_UNAVAILABLE)
    if (
        intent.payload != expected
        or intent.interrupt_state != InterruptState.NONE
        or stored.request_id != row.pk
        or (original.registration_id, original.organization_uuid, original.project_id)
        != (row.pk, row.organization_uuid, row.project_id)
    ):
        raise ValueError(_UNAVAILABLE)
    return original


def _validate_capture_authority(
    row: GcpRangeProject, intent: ProvisionerLaunchIntent, stored: OperationInput, original: GcpProjectRegistrationInput
) -> None:
    """Reconstruct the exact initiating proof and immutable payload digest."""
    from ._gcp_project_registration import project_authority_fields

    authority = project_authority_fields(credential_reference_from_record(intent), row)
    if any(getattr(intent, name) != value for name, value in authority.items()):
        raise ValueError(_UNAVAILABLE)
    if canonical_payload_digest(original.model_dump(mode="json")) != canonical_payload_digest(
        stored.envelope["payload"]
    ):
        raise ValueError(_UNAVAILABLE)


def authorize_project_operation(payload: dict[str, object], operation_id: UUID | str | None) -> None:
    """Recheck the initiating credential and installation action immediately before launch."""
    from ._gcp_project_registration import project_authority_fields, require_project_administrator

    try:
        row = validate_project_operation(payload, operation_id)
        intent = ProvisionerLaunchIntent.objects.get(operation_id=UUID(str(operation_id)))
        current = require_project_administrator(credential_reference_from_record(intent))
        expected = project_authority_fields(current, row)
        if any(getattr(intent, name) != value for name, value in expected.items()):
            raise ValueError(_UNAVAILABLE)
    except Exception:  # noqa: BLE001  # revoked proof, configuration and persistence failures deny all effects
        raise PermissionError(_UNAVAILABLE) from None
