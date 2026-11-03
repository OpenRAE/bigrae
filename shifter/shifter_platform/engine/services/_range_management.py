"""Apply only explicitly requested private host access for the exact operation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.range_management import validate_management_access, validate_management_targets

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, Range


def persist_realized_management(row: OperationResultInbox, payload: dict[str, object], runtime: Range) -> None:
    from engine.models import OperationInput, RangeManagementAccess

    immutable = OperationInput.objects.filter(operation_id=row.operation_id).first()
    input_payload = immutable.envelope["payload"] if immutable is not None else {}
    targets = validate_management_targets(input_payload.get("management_targets", []), input_payload.get("plan", {}))
    realized = validate_management_access(payload.get("management_access", {}))
    expected = {f"{target}#0" for target in targets}
    if set(realized) != expected or not expected.issubset({item["uuid"] for item in runtime.provisioned_instances}):
        raise ValueError("Management projection does not match admitted targets")
    if targets:
        if runtime.resource_generation is None:
            raise ValueError("Management resource generation is unavailable")
        RangeManagementAccess.objects.update_or_create(
            range=runtime,
            defaults={
                "operation_id": row.operation_id,
                "resource_generation": runtime.resource_generation,
                "bindings": realized,
            },
        )
