"""Retain exact project references in native preparation, retries and cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

from shared.gcp_range_projects import GcpProjectLease
from shared.operation_envelope import validate_operation_envelope
from shared.raes.gcp_project_demands import planned_gcp_project_demands
from shared.raes.operation_input import parse_raes_operation_input

if TYPE_CHECKING:
    from engine.models import Range
    from shared.runtime_plugin_binding import RuntimePin

_UNAVAILABLE = "Registered project input is unavailable"


def allocate_plan_projects(target: Range, plan: dict[str, Any], original_digest: str) -> tuple[GcpProjectLease, ...]:
    """Reserve only native concrete project demands under the existing Range mutex."""
    from engine.models import GcpRangeProjectUse

    from ._gcp_project_bindings import allocate_gcp_projects

    demands = planned_gcp_project_demands(plan)
    if not demands:
        if GcpRangeProjectUse.objects.filter(range=target).exists():
            raise ValueError(_UNAVAILABLE)
        return ()
    if not transaction.get_connection().in_atomic_block:
        raise ValueError(_UNAVAILABLE)
    with transaction.atomic():
        leases = allocate_gcp_projects(
            range_id=target.pk,
            project_ids=sorted({demand.project_id for demand in demands}),
            plan_digest=original_digest,
        )
        by_project = {lease.project_id: lease for lease in leases}
        if any(
            demand.project_number and demand.project_number != by_project[demand.project_id].project_number
            for demand in demands
        ):
            raise ValueError(_UNAVAILABLE)
        return leases


def retained_project_leases(target: Range) -> tuple[GcpProjectLease, ...]:
    """Scope changes cannot transplant a still-held project to another organization."""
    from engine.models import GcpRangeProjectUse

    from ._range_authority import project_range_authority

    leases = tuple(
        GcpProjectLease.model_validate(row.binding)
        for row in GcpRangeProjectUse.objects.filter(range=target, released_at__isnull=True).order_by(
            "project__project_id"
        )
    )
    if not leases:
        return ()
    if target.request is None:
        raise ValueError(_UNAVAILABLE)
    projection = project_range_authority(target.request.request_id)
    for lease in leases:
        if (lease.range_id, lease.range_uuid, lease.request_id, lease.organization_uuid) != (
            target.pk,
            target.uuid,
            target.request.request_id,
            projection.scope.organization_uuid,
        ):
            raise ValueError(_UNAVAILABLE)
    return leases


def projects_for_input(target: Range, plan: dict[str, Any], pin: RuntimePin | None) -> tuple[GcpProjectLease, ...]:
    """Project only retained custody; an input projection never grants a new lease."""
    if pin is not None and "provision.prepare" in pin.manifest.capabilities:
        return ()
    leases = retained_project_leases(target)
    demands = planned_gcp_project_demands(plan)
    if {demand.project_id for demand in demands} != {lease.project_id for lease in leases}:
        raise ValueError(_UNAVAILABLE)
    if any(lease.plan_digest != canonical_digest(plan) for lease in leases):
        raise ValueError(_UNAVAILABLE)
    return leases


def allocate_launch_projects(payload: dict[str, object], operation_id: UUID | str) -> None:
    """Called only after native launch admission, in its outbox transaction."""
    from engine.models import Range

    from ._runtime_plugin_bindings import retained_runtime_plugin_pin

    if (payload.get("resource"), payload.get("operation")) != ("raes-range", "provision"):
        return
    if not transaction.get_connection().in_atomic_block:
        raise ValueError(_UNAVAILABLE)
    target = (
        Range.objects.select_for_update(of=("self",))
        .select_related("request")
        .get(
            request__request_id=str(payload["request_id"]),
            provisioner_operation_id=operation_id,
        )
    )
    pin = retained_runtime_plugin_pin(target)
    if pin is not None and "provision.prepare" in pin.manifest.capabilities:
        return
    plan = target.range_config or {}
    leases = allocate_plan_projects(target, plan, canonical_digest(plan))
    validate_project_preparation(target.raes_cloud_content, plan, plan, leases)


def validate_project_preparation(
    sealed: dict[str, Any] | None,
    original: dict[str, Any],
    effective: dict[str, Any],
    leases: tuple[GcpProjectLease, ...],
    result: RuntimePlan | None = None,
    pin: RuntimePin | None = None,
) -> None:
    """Admit all concrete native cloud shapes and payloads before committing custody."""
    from shared.field_encryption import decrypt_value
    from shared.gcp_cloud_content import CloudContentEnvelope, open_cloud_content
    from shared.gcp_runtime_plan import compile_cloud_work, selected_secret_payloads

    envelope = CloudContentEnvelope.model_validate(sealed) if sealed is not None else None
    contents = open_cloud_content(envelope, original, decrypt_value)
    if result is not None and pin is not None:
        contents.update(selected_secret_payloads(original, result, pin.manifest.provisioning_concerns))
    compile_cloud_work(effective, leases, contents)


def retained_project_cleanup_payload(target: Range) -> dict[str, Any] | None:
    """Recover original projections without a new image/material registry selection."""
    from engine.models import OperationInput

    leases = retained_project_leases(target)
    if not leases:
        return None
    if target.request is None or len({lease.source_operation_id for lease in leases}) != 1:
        raise ValueError(_UNAVAILABLE)
    source = OperationInput.objects.get(
        operation_id=leases[0].source_operation_id, request_id=target.request.request_id
    )
    envelope = validate_operation_envelope(source.envelope)
    if (envelope["resource"], envelope["operation"]) != ("raes-range", "provision"):
        raise ValueError(_UNAVAILABLE)
    original = parse_raes_operation_input(envelope["payload"])
    if original.gcp_projects != leases:
        raise ValueError(_UNAVAILABLE)
    return dict(envelope["payload"])
