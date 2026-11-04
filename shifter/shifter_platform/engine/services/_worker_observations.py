"""Apply credential-free worker observations for the exact admitted operation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.range_management import validate_management_targets
from shared.worker_observations import validate_worker_observations

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, Range


def persist_worker_observations(row: OperationResultInbox, payload: dict[str, object], runtime: Range) -> None:
    """Retain safe facts only for admitted targets and the accepted generation."""
    from engine.models import OperationInput, WorkerHostObservation

    if row.operation_id != runtime.provisioner_operation_id:
        raise ValueError("Worker observation operation changed")
    immutable = OperationInput.objects.filter(operation_id=row.operation_id).first()
    input_payload = immutable.envelope["payload"] if immutable is not None else {}
    targets = validate_management_targets(input_payload.get("management_targets", []), input_payload.get("plan", {}))
    realized = validate_worker_observations(payload.get("worker_observations", {}))
    if not isinstance(runtime.provisioned_instances, list):
        raise ValueError("Worker observation membership is unavailable")
    expected = {f"{target}#0" for target in targets}
    if set(realized) != expected or not expected.issubset({item["uuid"] for item in runtime.provisioned_instances}):
        raise ValueError("Worker observation projection does not match admitted targets")
    if targets:
        if runtime.resource_generation is None:
            raise ValueError("Worker observation resource generation is unavailable")
        WorkerHostObservation.objects.update_or_create(
            range=runtime,
            defaults={
                "operation_id": row.operation_id,
                "resource_generation": runtime.resource_generation,
                "observations": realized,
            },
        )
