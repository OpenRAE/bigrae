"""Validated durable intents for privileged provisioner Job launches."""

from __future__ import annotations

from functools import partial
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from engine.ecs._local import _is_local_provisioner_enabled
from engine.ecs._workload import provisioner_workload
from engine.launch_commands import command_from_payload, validate_provisioner_command
from engine.models import (
    Instance,
    ProvisionerLaunchIntent,
    ProvisionerLaunchStatus,
    Range,
)
from engine.services._gcp_project_inputs import allocate_launch_projects
from engine.services._launch_authority import (
    assert_admitted_launch_binding,
    assert_launch_authority_replay,
    prepare_launch_authority,
)

# The dispatch-failure lifecycle lives in its own module (Sonar S104); re-exported
# here so existing ``from engine.services._launch_intents import ...`` importers are unaffected.
from engine.services._launch_generation import _assert_stored_intent_matches, _lock_operation_target
from engine.services._launch_intents_failure import (
    PROVISIONER_DISPATCH_FAILED,
    clear_provisioner_operation_after_failure,
    fail_current_provisioner_operation,
)
from engine.services._launch_interrupt import request_provision_interrupt
from engine.services._launch_outbox import drain_local_intent
from engine.services._launch_payload_authority import authorize_provisioner_payload as authorize_provisioner_payload
from engine.services._operation_inputs import materialize_operation_input
from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.kubernetes.naming import build_idempotent_job_name
from shared.credentials import CredentialContext

if TYPE_CHECKING:
    from typing import Any
    from uuid import UUID

    from shared.credentials import CredentialContext


# Public surface, including the dispatch-failure names re-exported from
# ``launch_intents_failure`` (Sonar S104 split) so existing importers are unaffected.
__all__ = [
    "PROVISIONER_DISPATCH_FAILED",
    "authorize_provisioner_payload",
    "clear_provisioner_operation_after_failure",
    "command_from_payload",
    "enqueue_provisioner_launch",
    "fail_current_provisioner_operation",
    "request_provision_interrupt",
    "task_ref_for_intent",
    "validate_provisioner_command",
]


def _should_rotate_generation(row: Range | Instance, operation: str) -> bool:
    """Return whether the domain row needs a fresh operation generation."""
    if row.provisioner_operation != operation or row.provisioner_operation_id is None:
        return True
    intent = ProvisionerLaunchIntent.objects.filter(operation_id=row.provisioner_operation_id).first()
    return intent is not None and (
        intent.status == ProvisionerLaunchStatus.DLQ
        or (intent.status == ProvisionerLaunchStatus.SUCCEEDED and row.status == "failed")
    )


def _operation_identity(payload: dict[str, object], authority: dict[str, object]) -> UUID:
    """Return the stable identity of the current authorized domain operation."""
    operation = f"{payload['resource']}:{payload['operation']}"
    with transaction.atomic():
        row = _lock_operation_target(payload)

        assert_admitted_launch_binding(authority, row)
        authorize_provisioner_payload(payload, target=row)
        current = (
            ProvisionerLaunchIntent.objects.filter(operation_id=row.provisioner_operation_id).first()
            if row.provisioner_operation_id is not None
            else None
        )
        cleanup_transition = (
            authority.get("authority_kind") == "cleanup"
            and current is not None
            and current.authority_kind in {"principal", "warm_pool"}
            and authority.get("cleanup_origin_operation_uuid") == current.operation_id
        )
        if _should_rotate_generation(row, operation) or cleanup_transition:
            row.provisioner_operation = operation
            row.provisioner_operation_id = uuid4()
            row.save(update_fields=["provisioner_operation", "provisioner_operation_id"])
        operation_id = row.provisioner_operation_id
        assert operation_id is not None, "operation generation must be reserved"
        return operation_id


def _materialize_operation_input(payload: dict[str, object], operation_id: UUID) -> None:
    """Keep input and launch intent inside their existing shared transaction."""

    materialize_operation_input(payload, operation_id, _lock_operation_target(payload))


def enqueue_provisioner_launch(
    command: list[str], *, credential: CredentialContext | None = None, cleanup_for: UUID | None = None
) -> str:
    """Persist one durable intent per authorized operation and return its UUID."""
    payload = validate_provisioner_command(command)

    authority = prepare_launch_authority(payload, credential, cleanup_for)
    return _enqueue_admitted_provisioner_launch(command, payload, authority)


def _enqueue_admitted_provisioner_launch(
    command: list[str], payload: dict[str, object], authority: dict[str, object]
) -> str:
    """Commit server-owned admission in the incumbent operation transaction."""

    with transaction.atomic():
        operation_id = _operation_identity(payload, authority)

        allocate_launch_projects(payload, operation_id)
        existing = ProvisionerLaunchIntent.objects.filter(operation_id=operation_id).first()
        if existing is not None:
            assert_launch_authority_replay(existing, authority)
            _assert_stored_intent_matches(payload, operation_id)
            return str(existing.intent_id)
        canonical = f"{'|'.join(command)}|{operation_id}"
        idempotency_key = sha256(canonical.encode("utf-8")).hexdigest()
        existing = ProvisionerLaunchIntent.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return str(existing.intent_id)
        intent_id = uuid4()
        namespace = str(getattr(settings, "ENGINE_TASK_CLUSTER", "") or "")
        task_ref = (
            f"{namespace}/{build_idempotent_job_name(PROVISIONER_CONTAINER_NAME, str(intent_id))}" if namespace else ""
        )
        row = ProvisionerLaunchIntent.objects.create(
            intent_id=intent_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            payload=payload,
            task_ref=task_ref,
            next_attempt_at=timezone.now(),
            **({"executing_workload": _launch_workload(payload, operation_id, intent_id)} if authority else {}),
            **authority,
        )
        _materialize_operation_input(payload, operation_id)

        if _is_local_provisioner_enabled():
            transaction.on_commit(partial(drain_local_intent, intent_id))
        return str(row.intent_id)


def _launch_workload(payload: dict[str, Any], operation_id: UUID | str, intent_id: UUID) -> dict[str, object]:
    """Bind the canonical command to its deterministic native task identity."""

    return provisioner_workload(command_from_payload({**payload, "operation_id": str(operation_id)}), str(intent_id))


def task_ref_for_intent(intent_id: str) -> str:
    """Return the provider task reference reserved for a queued intent."""
    return ProvisionerLaunchIntent.objects.only("task_ref").get(intent_id=UUID(intent_id)).task_ref
