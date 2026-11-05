"""Consume application-approved preparation without importing RAES or domain models."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from shared.gcp_runtime_plan import selected_secret_payloads
from shared.runtime_plugin_binding import runtime_plugin_requests
from shared.runtime_plugin_preparation import RuntimePreparation, apply_prepared_values
from shifter_adapter_sdk.runtime import MAX_PREPARATION_BYTES, RuntimePlan, canonical_digest, decode_message

from config._crypto import decrypt_field
from provisioner_db_operation_input import RaesOperationRun

_UNAVAILABLE = "Runtime preparation is unavailable"


def approved_plan(run: RaesOperationRun, record: object) -> RuntimePlan:
    """Authenticate retained approval against its original operation and immutable pin."""
    try:
        return _approved_plan(run, record)
    except Exception:  # noqa: BLE001  # decrypted validation diagnostics must never reach the task log
        raise ValueError(_UNAVAILABLE) from None


def _approved_plan(run: RaesOperationRun, record: object) -> RuntimePlan:
    """Check the sealed response against its reconstructed source request."""
    pin = run.input.runtime_plugin
    snapshot = _bound_snapshot(run, record)
    if (
        pin is None
        or snapshot.state != "prepared"
        or snapshot.source_operation_id is None
        or snapshot.encrypted_result is None
        or run.input.range_backend not in {"gce", "ec2"}
    ):
        raise ValueError(_UNAVAILABLE)
    requests = runtime_plugin_requests(
        pin,
        run.input.plan,
        snapshot.source_operation_id,
        run.input.legacy_range_id,
        backend=run.input.range_backend,
    )
    request = next(item for item in requests if item.phase == "prepare")
    if snapshot.input_digest != request.digest:
        raise ValueError(_UNAVAILABLE)
    raw = decrypt_field(snapshot.encrypted_result)
    result = RuntimePlan.model_validate(decode_message(raw, limit=MAX_PREPARATION_BYTES))
    result.authorize(request)
    if result.status != "planned":
        raise ValueError(_UNAVAILABLE)
    return result


def _bound_snapshot(run: RaesOperationRun, record: object) -> RuntimePreparation:
    """Bind every retained state to the original plan and executable."""
    pin = run.input.runtime_plugin
    snapshot = RuntimePreparation.model_validate(record)
    if pin is None or snapshot.pin_digest != pin.digest or snapshot.plan_digest != canonical_digest(run.input.plan):
        raise ValueError(_UNAVAILABLE)
    for lease in snapshot.cloud_projects:
        lease.authorize(
            request_id=UUID(run.request_id), range_id=run.input.legacy_range_id, plan_digest=snapshot.plan_digest
        )
    return snapshot


def prepared_run(
    run: RaesOperationRun, result: RuntimePlan | None, snapshot: RuntimePreparation | None = None
) -> RaesOperationRun:
    """Create an execution-only copy; reports continue to use authored identities."""
    pin = run.input.runtime_plugin
    if pin is None or "provision.prepare" not in pin.manifest.capabilities:
        if result is not None or snapshot is not None:
            raise ValueError(_UNAVAILABLE)
        return run
    if result is None or snapshot is None:
        raise ValueError(_UNAVAILABLE)
    snapshot = _bound_snapshot(run, snapshot)
    if snapshot.state != "prepared":
        raise ValueError(_UNAVAILABLE)
    plan = apply_prepared_values(run.input.plan, result, pin.manifest.provisioning_concerns)
    payloads = selected_secret_payloads(run.input.plan, result, pin.manifest.provisioning_concerns)
    return RaesOperationRun(
        run.operation_id,
        run.request_id,
        replace(
            run.input,
            plan=plan,
            gcp_projects=snapshot.cloud_projects,
            runtime_preparation=snapshot,
            secret_payloads=payloads,
        ),
    )


def cleanup_preparation(run: RaesOperationRun) -> tuple[RaesOperationRun, dict[str, Any] | None]:
    """Use retained selections, or the mutex-proven absence of any provisioning effect."""
    pin = run.input.runtime_plugin
    if pin is None or "provision.prepare" not in pin.manifest.capabilities:
        return run, None
    snapshot = run.input.runtime_preparation
    if snapshot is None:
        raise ValueError(_UNAVAILABLE)
    snapshot = _bound_snapshot(run, snapshot)
    if snapshot.state == "unprepared":
        # The Engine snapshots this under the same Range lock used to accept
        # preparation. No consumer can cross the first-effect barrier without
        # that acceptance, and a late acceptance is fenced by the destroy epoch.
        return run, {
            "outcome": "VERIFIED_ABSENT",
            "residual_categories": [],
            "scope": {
                "proof": "runtime-preparation-not-accepted/v1",
                "plan_digest": snapshot.plan_digest,
                "pin_digest": snapshot.pin_digest,
                "request_id": run.request_id,
                "operation_id": run.operation_id,
            },
        }
    return prepared_run(run, approved_plan(run, snapshot), snapshot), None
