"""Operation-fenced planning requests; plugin code runs only in isolated Jobs."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import OperationInput, RuntimePluginInstallation, RuntimePluginInvocation

from django.db import transaction
from django.utils import timezone
from shifter_adapter_sdk.runtime import RuntimeInput, RuntimePlan

from shared.cloud.runtime_plugins import interrupt_plugin, launch_plugin, observe_plugin
from shared.operation_envelope import validate_operation_envelope
from shared.raes.operation_input import RaesOperationInput, parse_raes_operation_input
from shared.runtime_file_inputs import RuntimeFileBinding, load_file_input_material
from shared.runtime_plugin_binding import runtime_plugin_requests
from shared.runtime_plugin_preparation import RuntimePreparation

from ._runtime_plugin_cleanup import preparation_cleanup_payload
from ._runtime_plugin_controller import _file_secret, _pull_secret
from ._runtime_plugin_preparation import (
    approve_invocation,
    preparation_result_secret,
    retain_preparation,
    retained_preparation,
)

logger = logging.getLogger(__name__)


def queue_runtime_plugin_plans(envelope: dict[str, Any]) -> None:
    """Called in the launch transaction; never imports the installed distribution."""
    from engine.models import RuntimePluginInvocation

    if (envelope["resource"], envelope["operation"]) != ("raes-range", "provision"):
        return
    if "runtime_plugin" not in envelope["payload"]:
        return
    parsed = parse_raes_operation_input(envelope["payload"])
    if parsed.runtime_plugin is None:
        return
    if parsed.range_backend not in {"gce", "ec2"}:
        raise ValueError("Runtime plugins are not supported by this range backend")
    from uuid import UUID

    requests = runtime_plugin_requests(
        parsed.runtime_plugin,
        parsed.plan,
        UUID(str(envelope["operation_id"])),
        parsed.legacy_range_id,
        backend=parsed.range_backend,
    )
    retained = _retained_for_operation(parsed, envelope)
    rows = []
    for request in requests:
        row = RuntimePluginInvocation(
            id=request.invocation_id,
            operation_id=request.operation_id,
            request_id=envelope["request_id"],
            phase=request.phase,
            input=request.model_dump(mode="json"),
            input_digest=request.digest,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        if request.phase == "prepare" and retained is not None and retained.state == "prepared":
            row.state = "planned"
            row.result = retained.model_dump(mode="json")
        rows.append(row)
    RuntimePluginInvocation.objects.bulk_create(rows)


def _retained_for_operation(parsed: RaesOperationInput, envelope: dict[str, Any]) -> RuntimePreparation | None:
    """Reserve enough transport budget even for cancellation before preparation."""
    from engine.models import Range

    pin = parsed.runtime_plugin
    if pin is None or "provision.prepare" not in pin.manifest.capabilities:
        return None
    record = retained_preparation(Range.objects.get(pk=parsed.legacy_range_id), pin)
    if record is None:
        raise ValueError("Runtime preparation is unavailable")
    preparation_cleanup_payload(envelope, record)
    return record


def _verify_operation_identity(operation: OperationInput, envelope: dict[str, Any]) -> None:
    """Reject a durable envelope whose correlation fields differ from its operation."""
    if any(
        str(envelope[key]) != str(getattr(operation, key))
        for key in (
            "operation_id",
            "request_id",
            "resource",
            "operation",
            "contract_version",
        )
    ) or (operation.resource, operation.operation) != ("raes-range", "provision"):
        raise ValueError("Plugin operation identity mismatch")


def _authorized_request(
    row: RuntimePluginInvocation,
) -> tuple[RuntimeInput, RuntimePluginInstallation, dict[str, RuntimeFileBinding]]:
    """Reconstruct the authorized request from durable operation and executable pins."""
    from engine.models import InterruptState, OperationInput, ProvisionerLaunchIntent, Range, RuntimePluginInstallation

    intent = ProvisionerLaunchIntent.objects.get(operation_id=row.operation_id)
    if intent.interrupt_state != InterruptState.NONE:
        raise ValueError("Plugin operation was interrupted")
    operation = OperationInput.objects.get(operation_id=row.operation_id, request_id=row.request_id)
    envelope = validate_operation_envelope(operation.envelope)
    _verify_operation_identity(operation, envelope)
    parsed = parse_raes_operation_input(envelope["payload"])
    pin = parsed.runtime_plugin
    if pin is None or parsed.range_backend not in {"gce", "ec2"}:
        raise ValueError("Missing plugin operation binding")
    target = Range.objects.get(request__request_id=row.request_id, provisioner_operation_id=row.operation_id)
    if target.id != parsed.legacy_range_id or target.status in {"destroyed", "destroying", "failed", "ready"}:
        raise ValueError("Plugin operation is no longer active")
    requests = runtime_plugin_requests(
        pin, parsed.plan, row.operation_id, parsed.legacy_range_id, backend=parsed.range_backend
    )
    request = _verify_invocation(row, requests)
    installation = RuntimePluginInstallation.objects.get(
        pk=pin.installation_id, organization_uuid=pin.organization_uuid
    )
    if installation.manifest_digest != pin.manifest.digest:
        raise ValueError("Plugin executable identity mismatch")
    return request, installation, pin.files


def _verify_invocation(row: RuntimePluginInvocation, requests: tuple[RuntimeInput, ...]) -> RuntimeInput:
    """Verify the durable phase request against the reconstructed immutable operation."""
    expected = next(request for request in requests if request.invocation_id == row.id)
    request = RuntimeInput.model_validate(row.input)
    if request.digest != expected.digest or row.input_digest != expected.digest or row.phase != expected.phase:
        raise ValueError("Plugin invocation identity mismatch")
    return request


def reconcile_runtime_plugin_operations(*, limit: int = 6) -> int:
    """Reconcile a bounded batch of pending isolated planning invocations."""
    from engine.models import RuntimePluginInvocation

    if not 1 <= limit <= 30:
        raise ValueError("Invalid plugin reconciliation batch size")
    rows = list(RuntimePluginInvocation.objects.filter(state="pending").order_by("updated_at", "id")[:limit])
    for row in rows:
        _reconcile(row)
    return len(rows)


def _observe_plan(request: RuntimeInput) -> tuple[RuntimePlan | None, str]:
    """Authorize the isolated worker result before accepting its planned state."""
    state = "pending"
    result = (
        observe_plugin(request, result_secret=preparation_result_secret(request))
        if request.phase == "prepare"
        else observe_plugin(request)
    )
    if result is not None:
        if not isinstance(result, RuntimePlan):
            raise ValueError("Invalid plugin plan")
        result = RuntimePlan.model_validate(result)
        result.authorize(request)
        state = "planned" if result.status == "planned" else "failed"
    return result, state


def _invocation_material(
    row: RuntimePluginInvocation,
    request: RuntimeInput,
    installation: RuntimePluginInstallation,
    files: dict[str, RuntimeFileBinding],
) -> tuple[RuntimePluginInstallation, dict[str, bytes]]:
    """Load exact bytes, then recheck generation and cancellation before any Job."""
    material = load_file_input_material(row.request_id, files)
    if files:
        current_request, installation, current_files = _authorized_request(row)
        if current_request != request or current_files != files or row.expires_at <= timezone.now():
            raise ValueError("Plugin planning changed during file preparation")
    return installation, material


def _launch_observation(
    row: RuntimePluginInvocation,
    request: RuntimeInput,
    installation: RuntimePluginInstallation,
    files: dict[str, RuntimeFileBinding],
) -> tuple[RuntimePlan | None, str, RuntimePreparation | None]:
    """Launch an isolated worker and validate its response before the commit fence."""
    approval = None
    installation, material = _invocation_material(row, request, installation, files)
    secret_name = f"runtime-plugin-pull-{request.invocation_id.hex}" if installation.registry_credentials else ""
    if request.phase == "prepare":
        launch_plugin(request, image_pull_secret=secret_name, result_secret=preparation_result_secret(request))
    else:
        launch_plugin(request, image_pull_secret=secret_name)
    _file_secret(request, material)
    _pull_secret(installation, request)
    result, state = _observe_plan(request)
    if result is not None and request.phase == "prepare" and state == "planned":
        approval = approve_invocation(row, request, result)
    return result, state, approval


def _reconcile(row: RuntimePluginInvocation) -> None:
    """Record only planning evidence still authorized by the locked range generation."""
    result, state = None, "pending"
    request = None
    approval = None
    try:
        request, installation, files = _authorized_request(row)
        if row.expires_at <= timezone.now():
            raise ValueError("Plugin planning expired")
        result, state, approval = _launch_observation(row, request, installation, files)
    except Exception as exc:  # noqa: BLE001  # plugin and registry errors can carry private output; log the type only
        # Private code, scripts and registry diagnostics never enter public logs.
        state = "failed"
        result = None
        logger.warning(
            "runtime plugin planning failed invocation_id=%s operation_id=%s exc_type=%s",
            row.pk,
            row.operation_id,
            type(exc).__name__,
        )
        if request is not None:
            # The Job deadline still bounds execution if interruption is unavailable.
            with suppress(Exception):
                interrupt_plugin(request)
    _persist_observation(row, state, result, approval)


def _persist_observation(
    row: RuntimePluginInvocation,
    state: str,
    result: RuntimePlan | None,
    approval: RuntimePreparation | None,
) -> None:
    """Commit accepted mapping and planned projection under the same generation lock."""
    from engine.models import Range, RuntimePluginInvocation

    with transaction.atomic():
        target = Range.objects.select_for_update().filter(request__request_id=row.request_id).first()
        current = RuntimePluginInvocation.objects.select_for_update().get(pk=row.pk)
        if current.state != "pending":
            return
        try:
            _authorized_request(current)
            if current.expires_at <= timezone.now():
                raise ValueError("Plugin planning expired")
            if approval is not None:
                if target is None:
                    raise ValueError("Plugin range is unavailable")
                approval = retain_preparation(target, approval)
        except Exception as exc:  # noqa: BLE001  # fail-closed recheck; input errors can carry private plan content
            if state != "failed":
                logger.warning(
                    "runtime plugin planning revoked at commit invocation_id=%s operation_id=%s exc_type=%s",
                    row.pk,
                    row.operation_id,
                    type(exc).__name__,
                )
            state, result = "failed", None
        current.state = state
        current.result = _result_payload(state, result, approval)
        current.save(update_fields=["state", "result", "updated_at"])


def _result_payload(
    state: str,
    result: RuntimePlan | None,
    approval: RuntimePreparation | None,
) -> dict[str, Any] | None:
    """Persist only sealed accepted preparation or an ordinary bounded phase result."""
    if approval is not None and state == "planned":
        return approval.model_dump(mode="json")
    if result is not None:
        return result.model_dump(mode="json")
    return None
