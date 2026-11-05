"""Exclusive registered-project allocation under the native Range mutex."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from pydantic import Field, TypeAdapter
from shifter_adapter_sdk.runtime import Digest

from engine.models import GcpRangeProject, GcpRangeProjectUse, InterruptState, ProvisionerLaunchIntent, Range
from shared.gcp_range_projects import MAX_PROJECTS_PER_RANGE, GcpBaselineRef, GcpProjectLease, ProjectID

from ._range_authority import project_range_authority

_UNAVAILABLE = "Registered project binding is unavailable"
_PROJECTS: TypeAdapter[list[str]] = TypeAdapter(Annotated[list[ProjectID], Field(max_length=MAX_PROJECTS_PER_RANGE)])
_DIGEST = TypeAdapter(Digest)


def allocate_gcp_projects(*, range_id: int, project_ids: list[str], plan_digest: str) -> tuple[GcpProjectLease, ...]:
    """Atomically reserve the exact authored projects; retries retain the original leases.

    This internal operation grants no launch authority. Its caller must admit the
    native launch/preparation first. Organization custody comes from the owning
    Range service, never a caller-supplied organization or scenario document.
    """
    from ._gcp_project_registration import protected_project_ids

    try:
        identifiers = _PROJECTS.validate_python(project_ids)
        digest = _DIGEST.validate_python(plan_digest)
        if len(set(identifiers)) != len(identifiers) or set(identifiers) & set(protected_project_ids()):
            raise ValueError(_UNAVAILABLE)
        with transaction.atomic():
            target = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=range_id)
            _require_allocation_state(target)
            if target.request is None or target.provisioner_operation_id is None:
                raise ValueError(_UNAVAILABLE)
            projection = project_range_authority(target.request.request_id)
            if projection.native_id != target.pk or projection.scope.organization_uuid is None:
                raise ValueError(_UNAVAILABLE)
            projects = _registered_projects(identifiers, projection.scope.organization_uuid)
            existing = tuple(GcpRangeProjectUse.objects.filter(range=target).order_by("project__project_id"))
            if existing:
                return _retained_bindings(target, existing, identifiers, digest)
            leases = [
                _reserve_project(project, target, digest, projection.scope.organization_uuid) for project in projects
            ]
            return tuple(sorted(leases, key=lambda lease: lease.project_id))
    except (ValueError, IntegrityError, Range.DoesNotExist):
        raise ValueError(_UNAVAILABLE) from None


def _registered_projects(identifiers: list[str], organization_uuid: UUID) -> list[GcpRangeProject]:
    """Lock the complete project selection in stable order and verify its organization."""
    projects = list(GcpRangeProject.objects.select_for_update().filter(project_id__in=identifiers).order_by("pk"))
    if len(projects) != len(identifiers) or any(project.organization_uuid != organization_uuid for project in projects):
        raise ValueError(_UNAVAILABLE)
    return projects


def _reserve_project(project: GcpRangeProject, target: Range, digest: str, organization_uuid: UUID) -> GcpProjectLease:
    """Create one immutable use while the owning range and project rows are locked."""
    if (
        project.status != "ready"
        or project.organization_uuid != organization_uuid
        or GcpRangeProjectUse.objects.filter(project=project, released_at__isnull=True).exists()
    ):
        raise ValueError(_UNAVAILABLE)
    if target.request is None or target.provisioner_operation_id is None:
        raise ValueError(_UNAVAILABLE)
    lease = GcpProjectLease(
        lease_id=uuid4(),
        source_operation_id=target.provisioner_operation_id,
        project_id=project.project_id,
        project_number=project.project_number,
        organization_uuid=project.organization_uuid,
        range_uuid=target.uuid,
        range_id=target.pk,
        request_id=target.request.request_id,
        plan_digest=digest,
        baseline=GcpBaselineRef.model_validate(project.baseline),
    )
    if lease.baseline.registration_id != project.pk:
        raise ValueError(_UNAVAILABLE)
    GcpRangeProjectUse.objects.create(
        id=lease.lease_id, project=project, range=target, binding=lease.model_dump(mode="json")
    )
    return lease


def _require_allocation_state(target: Range) -> None:
    """A cancellation, wrong backend or terminal range cannot acquire new custody."""
    if (
        target.request is None
        or target.provisioner_operation_id is None
        or target.range_backend != "gce"
        or target.status not in {"pending", "provisioning"}
    ):
        raise ValueError(_UNAVAILABLE)
    if (
        ProvisionerLaunchIntent.objects.filter(operation_id=target.provisioner_operation_id)
        .exclude(interrupt_state=InterruptState.NONE)
        .exists()
    ):
        raise ValueError(_UNAVAILABLE)


def _retained_bindings(
    target: Range, uses: tuple[GcpRangeProjectUse, ...], identifiers: list[str], digest: str
) -> tuple[GcpProjectLease, ...]:
    """A retry cannot exchange projects, baselines, requests, ranges or plans."""
    if target.request is None:
        raise ValueError(_UNAVAILABLE)
    leases = tuple(GcpProjectLease.model_validate(use.binding) for use in uses)
    if sorted(identifiers) != [lease.project_id for lease in leases] or any(
        use.released_at is not None for use in uses
    ):
        raise ValueError(_UNAVAILABLE)
    for lease in leases:
        lease.authorize(request_id=target.request.request_id, range_id=target.pk, plan_digest=digest)
        if lease.range_uuid != target.uuid:
            raise ValueError(_UNAVAILABLE)
    return leases
