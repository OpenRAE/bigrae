"""One trial per disposable worker, through native ``worker-trial`` operations.

The caller stages the trial files and supplies an opaque owner reference. Engine
records the initiating authority, launches the provisioner, and applies its
closed receipt. ``run`` can start a trial; ``collect`` never starts one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from shared.disposable_workers import WorkerHostProfile
from shared.operation_envelope import build_operation_envelope
from shared.worker_trial import RUN_OVERDUE_SECONDS, StagedObject, WorkerTrialInput, parse_worker_trial_receipt

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, ProvisionerLaunchIntent, WorkerTrial
    from shared.credentials import CredentialContext

_RESOURCE = "worker-trial"
_OPERATIONS = frozenset({"run", "collect"})
_UNAVAILABLE = "Worker trial operation unavailable"


@dataclass(frozen=True)
class WorkerTrialView:
    """Bounded trial facts; no staged content or credential."""

    trial_id: UUID
    worker_id: UUID
    owner_reference: UUID
    state: str
    exit_code: int | None
    sealed: bool
    archive: dict[str, Any] | None
    operation: str
    stop_requested: bool
    operation_failed: bool
    operation_finished: bool
    overdue: bool


def _current_operation_id(trial: WorkerTrial) -> UUID:
    """Return the trial's current operation; every created trial has one."""
    if trial.provisioner_operation_id is None:
        raise ValueError(_UNAVAILABLE)
    return trial.provisioner_operation_id


def _view(trial: WorkerTrial) -> WorkerTrialView:
    """Project the trial and the state of its current operation."""
    from engine.models import ProvisionerLaunchIntent

    intent = ProvisionerLaunchIntent.objects.get(operation_id=_current_operation_id(trial))
    return WorkerTrialView(
        trial_id=trial.pk,
        worker_id=trial.worker_id,
        owner_reference=trial.owner_reference,
        state=trial.state,
        exit_code=trial.exit_code,
        sealed=trial.sealed,
        archive=trial.archive,
        operation=trial.provisioner_operation,
        stop_requested=trial.stop_requested,
        operation_failed=trial.operation_failed,
        operation_finished=_operation_finished(intent),
        overdue=timezone.now() > trial.deadline + timedelta(seconds=RUN_OVERDUE_SECONDS),
    )


def _range_authority(credential: CredentialContext, worker_request_id: UUID) -> dict[str, object]:
    """Record exact range-manage authority on the worker's native range."""
    from ._launch_authority import admit_launch_authority

    payload: dict[str, object] = {"resource": "raes-range", "request_id": str(worker_request_id), "operation": "trial"}
    return admit_launch_authority(payload, credential)


def start_worker_trial(
    credential: CredentialContext,
    worker_id: UUID,
    *,
    owner_reference: UUID,
    staged: dict[str, StagedObject],
    deadline: datetime,
) -> WorkerTrialView:
    """Create the worker's single trial and launch ``run``; an identical replay returns it."""
    from engine.models import WorkerTrial

    from ._disposable_workers import _authorized_worker
    from ._worker_qualification import has_current_qualification
    from ._worker_retirement import _lock_worker

    worker = _authorized_worker(credential, worker_id, "range.manage")
    fields = _range_authority(credential, worker.request_id)
    staged_json = {name: item.model_dump(mode="json") for name, item in staged.items()}
    with transaction.atomic():
        worker = _lock_worker(worker_id)
        existing = WorkerTrial.objects.select_for_update().filter(worker=worker).first()
        if existing is not None:
            if existing.owner_reference != owner_reference or existing.staged != staged_json:
                raise ValueError("Worker trial conflicts")
            return _view(existing)
        if worker.retirement_at is not None or worker.terminal_at is not None:
            raise ValueError("Worker is retiring")
        if (
            worker.range.provisioner_operation != "raes-range:provision"
            or worker.range.provisioner_operation_id is None
        ):
            raise ValueError("Worker provisioning is unavailable")
        if not has_current_qualification(worker):
            raise ValueError("Worker qualification is not current")
        trial = WorkerTrial.objects.create(
            worker=worker, owner_reference=owner_reference, deadline=deadline, staged=staged_json, **fields
        )
        _queue(trial, "run")
        return _view(trial)


def get_worker_trial(credential: CredentialContext, worker_id: UUID) -> WorkerTrialView:
    """Return the trial after current range-read authorization."""
    from engine.models import WorkerTrial

    from ._disposable_workers import _authorized_worker

    _authorized_worker(credential, worker_id, "range.read")
    return _view(WorkerTrial.objects.get(worker_id=worker_id))


def collect_worker_trial(credential: CredentialContext, worker_id: UUID, *, stop: bool = False) -> WorkerTrialView:
    """Stop and collect, or collect only. Never starts a trial.

    A running ``run`` operation is interrupted; its interrupt hook launches ``collect``.
    """
    from engine.launch_interrupt import _request_intent_interrupt
    from engine.models import ProvisionerLaunchIntent, WorkerTrial

    from ._disposable_workers import _authorized_worker

    _authorized_worker(credential, worker_id, "range.manage")
    with transaction.atomic():
        trial = WorkerTrial.objects.select_for_update().get(worker_id=worker_id)
        if stop and not trial.stop_requested:
            trial.stop_requested = True
            trial.save(update_fields=["stop_requested", "updated_at"])
        intent = ProvisionerLaunchIntent.objects.select_for_update().get(operation_id=_current_operation_id(trial))
        if not _operation_finished(intent):
            if stop and trial.provisioner_operation == "run":
                _request_intent_interrupt(intent)
        else:
            _queue(trial, "collect")
        return _view(trial)


def _operation_finished(intent: ProvisionerLaunchIntent) -> bool:
    """An operation ends with an applied terminal result or exhausted dispatch."""
    from engine.models import OperationResultDisposition, OperationResultInbox, ProvisionerLaunchStatus

    if intent.status == ProvisionerLaunchStatus.DLQ:
        return True
    return OperationResultInbox.objects.filter(
        operation_id=intent.operation_id,
        disposition=OperationResultDisposition.APPLIED,
        result_kind__in=("TERMINAL_SUCCESS", "TERMINAL_FAILURE"),
    ).exists()


def _payload(trial: WorkerTrial, operation: str) -> dict[str, object]:
    """Return the canonical launch payload for one trial operation."""
    return {
        "version": 1,
        "resource": _RESOURCE,
        "operation": operation,
        "request_id": str(trial.generation),
        "trial_id": str(trial.pk),
    }


def _input(trial: WorkerTrial) -> dict[str, object]:
    """Return the immutable provisioner input for the trial."""
    worker_range = trial.worker.range
    if worker_range.provisioner_operation_id is None:
        raise ValueError("Worker provisioning is unavailable")
    value = WorkerTrialInput(
        trial_id=trial.pk,
        generation=trial.generation,
        range_request_id=trial.worker.request_id,
        provision_operation_id=worker_range.provisioner_operation_id,
        deadline=trial.deadline.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        staged={name: StagedObject.model_validate(item) for name, item in trial.staged.items()},
        stop=trial.stop_requested,
        trial_host=WorkerHostProfile.model_validate(trial.worker.profile).trial_host,
    )
    return value.model_dump(mode="json")


def _queue(trial: WorkerTrial, operation: str) -> None:
    """Commit the launch intent, immutable input and audit together."""
    from engine.ecs._workload import provisioner_workload
    from engine.launch_intents import command_from_payload
    from engine.models import OperationInput, ProvisionerLaunchIntent
    from shared.db import RecordedAuthorityFields

    from ._launch_authority import authority_envelope_fields

    operation_id, intent_id = uuid4(), uuid4()
    payload = _payload(trial, operation)
    workload = provisioner_workload(
        command_from_payload({**payload, "operation_id": str(operation_id)}), str(intent_id)
    )
    fields = {field.name: getattr(trial, field.name) for field in RecordedAuthorityFields._meta.fields}
    intent = ProvisionerLaunchIntent.objects.create(
        operation_id=operation_id,
        intent_id=intent_id,
        idempotency_key=sha256(f"{_RESOURCE}:{trial.pk}:{operation_id}".encode()).hexdigest(),
        payload=payload,
        task_ref=f"{workload['namespace']}/{workload['job_name']}",
        next_attempt_at=timezone.now(),
        executing_workload=workload,
        **fields,
    )
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=trial.generation,
        resource=_RESOURCE,
        operation=operation,
        payload=_input(trial),
        **authority_envelope_fields(intent),
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=trial.generation,
        resource=_RESOURCE,
        operation=operation,
        contract_version=envelope["contract_version"],
        envelope=envelope,
    )
    trial.provisioner_operation_id = operation_id
    trial.provisioner_operation = operation
    trial.operation_failed = False
    trial.save(update_fields=["provisioner_operation_id", "provisioner_operation", "operation_failed", "updated_at"])
    _audit(trial, operation)


def _audit(trial: WorkerTrial, operation: str) -> None:
    """Audit a queued trial operation against the worker's range."""
    from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
    from shared.operation_authority import credential_reference_from_record

    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=trial.worker.range_id,
            action=AuditAction.UPDATE,
            **principal_actor_fields(credential_reference_from_record(trial).principal),
            new_state={"trial_uuid": str(trial.pk), "operation": operation},
            context="worker_trial_queued",
            request_id=str(trial.generation),
        ),
        strict=True,
    )


def validate_worker_trial_command(command: list[str]) -> dict[str, Any]:
    """Parse only the canonical ``worker-trial`` command."""
    if (
        len(command) != 6
        or command[0] != _RESOURCE
        or command[1] not in _OPERATIONS
        or command[2] != "--request-id"
        or command[4] != "--trial-id"
    ):
        raise ValueError(_UNAVAILABLE)
    return {
        "version": 1,
        "resource": _RESOURCE,
        "operation": command[1],
        "request_id": str(UUID(command[3])),
        "trial_id": str(UUID(command[5])),
    }


def validate_worker_trial_operation(payload: dict[str, Any], operation_id: UUID | str | None) -> WorkerTrial:
    """Fence the trial generation, current operation and immutable input."""
    from engine.models import OperationInput, ProvisionerLaunchIntent, WorkerTrial

    from ._launch_authority import assert_input_authority_binding

    trial = WorkerTrial.objects.select_related("worker__range__request").get(pk=UUID(str(payload["trial_id"])))
    if str(trial.generation) != payload["request_id"] or payload["operation"] not in _OPERATIONS:
        raise ValueError(_UNAVAILABLE)
    if operation_id is not None:
        if (
            trial.provisioner_operation_id != UUID(str(operation_id))
            or trial.provisioner_operation != payload["operation"]
        ):
            raise ValueError("Worker trial operation changed")
        intent = ProvisionerLaunchIntent.objects.get(operation_id=operation_id)
        stored = OperationInput.objects.get(operation_id=operation_id)
        if intent.payload != payload or stored.envelope["payload"]["trial_id"] != str(trial.pk):
            raise ValueError("Worker trial input changed")
        assert_input_authority_binding(stored, intent)
    return trial


def authorize_worker_trial_operation(payload: dict[str, Any], operation_id: UUID | str | None) -> None:
    """Recheck the recorded initiating proof against the worker's range."""
    from engine.models import ProvisionerLaunchIntent

    from ._launch_authority import authorize_launch_authority

    try:
        trial = validate_worker_trial_operation(payload, operation_id)
        if operation_id is not None:
            intent = ProvisionerLaunchIntent.objects.get(operation_id=operation_id)
            authorize_launch_authority(intent, trial.worker.range)
    except Exception:  # noqa: BLE001  # fail-closed authority check; every failure is one bounded denial
        raise PermissionError(_UNAVAILABLE) from None


def enqueue_interrupted_worker_trial(origin: ProvisionerLaunchIntent) -> bool:
    """After an interrupted ``run`` stops, collect with a stop request."""
    from engine.models import WorkerTrial

    with transaction.atomic():
        trial = WorkerTrial.objects.select_for_update().filter(pk=origin.payload.get("trial_id")).first()
        if trial is None:
            return False
        if trial.provisioner_operation_id == origin.operation_id:
            _queue(trial, "collect")
        return True


def mark_worker_trial_operation_failed(trial: WorkerTrial) -> None:
    """Record a failed operation without changing the observed trial facts."""
    trial.operation_failed = True
    trial.save(update_fields=["operation_failed", "updated_at"])


def fail_worker_trial_dispatch(payload: dict[str, Any], operation_id: UUID | str) -> bool:
    """Exhausted dispatch fails only the trial operation that still owns its generation."""
    from engine.models import WorkerTrial

    trial_id = payload.get("trial_id")
    if trial_id is None:
        return False
    trial = WorkerTrial.objects.select_for_update().filter(pk=trial_id, provisioner_operation_id=operation_id).first()
    if trial is None:
        return False
    mark_worker_trial_operation_failed(trial)
    return True


def apply_worker_trial_result(result: OperationResultInbox, payload: dict[str, Any]) -> tuple[str, str]:
    """Apply the closed receipt of the exact current operation."""
    from engine.models import OperationResultDisposition, WorkerTrial

    trial = WorkerTrial.objects.select_for_update().filter(provisioner_operation_id=result.operation_id).first()
    if trial is None or str(trial.generation) != str(result.request_id):
        return OperationResultDisposition.REJECTED_STALE, "worker trial generation is no longer current"
    if result.result_kind == "TERMINAL_FAILURE":
        mark_worker_trial_operation_failed(trial)
        return OperationResultDisposition.APPLIED, "worker trial operation failed"
    return _record_receipt(trial, payload)


def _record_receipt(trial: WorkerTrial, payload: dict[str, Any]) -> tuple[str, str]:
    """Record the observed trial facts from a receipt that names this trial."""
    from engine.models import OperationResultDisposition

    receipt = parse_worker_trial_receipt(payload)
    if receipt.trial_id != trial.pk:
        return OperationResultDisposition.REJECTED_OWNERSHIP, "receipt names another trial"
    trial.state = receipt.state
    trial.exit_code = receipt.exit_code
    trial.sealed = receipt.sealed
    if receipt.archive is not None:
        trial.archive = receipt.archive.model_dump(mode="json")
    trial.save(update_fields=["state", "exit_code", "sealed", "archive", "updated_at"])
    return OperationResultDisposition.APPLIED, f"worker trial {receipt.state}"
