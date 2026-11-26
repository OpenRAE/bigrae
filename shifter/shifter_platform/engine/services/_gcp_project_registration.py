"""Installation-authorized registration through the incumbent native outbox."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction
from pydantic import TypeAdapter

from engine.models import GcpRangeProject, RaesImageMapping
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.authorization import TargetRef
from shared.credentials import CredentialContext, resolve_credential_scope
from shared.exceptions import ValidationError
from shared.gcp_project_registration import (
    PROTECTED_IMAGE_ENV_NAMES,
    PROTECTED_PROJECT_ENV_NAMES,
    GcpProjectRegistrationInput,
    configured_project_ids,
)
from shared.gcp_range_projects import GcpBaselineRef, ProjectID

from ._gcp_project_authority import require_project_administrator
from ._gcp_project_operations import queue_project_registration

_UNAVAILABLE = "Registered project is unavailable"


@dataclass(frozen=True, slots=True)
class GcpRangeProjectView:
    """Installation-only projection; baseline inventory and object locators stay private."""

    id: UUID
    organization_uuid: UUID
    project_id: str
    project_number: str
    status: str
    failure_code: str
    in_use: bool


def project_registration_input(row: GcpRangeProject) -> GcpProjectRegistrationInput:
    """Snapshot storage and protected root configuration independently of caller input."""
    if settings.CLOUD_PROVIDER != "gcp":
        raise ValidationError(_UNAVAILABLE)
    try:
        protected = protected_project_ids()
        return GcpProjectRegistrationInput(
            registration_id=row.pk,
            organization_uuid=row.organization_uuid,
            project_id=row.project_id,
            bucket=str(settings.STORAGE_BUCKET_NAME)
            if row.baseline is None
            else GcpBaselineRef.model_validate(row.baseline).bucket,
            baseline=GcpBaselineRef.model_validate(row.baseline) if row.baseline is not None else None,
            protected_project_ids=protected,
        )
    except ValueError:
        raise ValidationError(_UNAVAILABLE) from None


def protected_project_ids() -> list[str]:
    """Deployment root and registered image stores cannot become scenario projects."""

    projects = (str(getattr(settings, name, os.environ.get(name, "")) or "") for name in PROTECTED_PROJECT_ENV_NAMES)
    images = [os.environ.get(name, "") for name in PROTECTED_IMAGE_ENV_NAMES]
    images.extend(RaesImageMapping.objects.filter(provider="gcp").values_list("image_ref", flat=True))
    return configured_project_ids(projects, images)


def register_gcp_range_project(
    credential: CredentialContext, organization_uuid: UUID, project_id: str
) -> GcpRangeProjectView:
    """Queue read-only baseline capture; never perform provider I/O in the portal."""

    current = require_project_administrator(credential)
    try:
        identifier = TypeAdapter(ProjectID).validate_python(project_id)
        organization = resolve_credential_scope(TargetRef("organization", organization_uuid))
        if organization.organization_uuid != organization_uuid:
            raise ValueError(_UNAVAILABLE)
    except Exception:  # noqa: BLE001  # provider identities and customer existence stay out of diagnostics
        raise ValidationError(_UNAVAILABLE) from None
    with transaction.atomic():
        current = require_project_administrator(current)
        row, created = GcpRangeProject.objects.get_or_create(
            project_id=identifier,
            defaults={"organization_uuid": organization_uuid, "created_by_principal_uuid": current.principal.uuid},
        )
        row = GcpRangeProject.objects.select_for_update().get(pk=row.pk)
        if row.organization_uuid != organization_uuid:
            raise ValidationError(_UNAVAILABLE)
        if created:
            original = project_registration_input(row)
            queue_project_registration(row, current, original)
            _audit_project(row, current, "register")
        return project_view(row)


def list_gcp_range_projects(
    credential: CredentialContext, *, cursor: UUID | None = None
) -> tuple[tuple[GcpRangeProjectView, ...], UUID | None]:
    """Return one bounded installation-only page in stable opaque-ID order."""

    require_project_administrator(credential)
    query = GcpRangeProject.objects.order_by("pk")
    if cursor is not None:
        query = query.filter(pk__gt=cursor)
    rows = list(query[:51])
    return tuple(project_view(row) for row in rows[:50]), rows[49].pk if len(rows) > 50 else None


def disable_gcp_range_project(credential: CredentialContext, registration_id: UUID) -> GcpRangeProjectView:
    """Stop new allocation without erasing an existing range's cleanup authority."""

    current = require_project_administrator(credential)
    with transaction.atomic():
        current = require_project_administrator(current)
        row = GcpRangeProject.objects.select_for_update().filter(pk=registration_id).first()
        if row is None:
            raise ValidationError(_UNAVAILABLE)
        row.status = "disabled"
        row.save(update_fields=["status", "updated_at"])
        _audit_project(row, current, "disable")
        return project_view(row)


def retry_gcp_range_project(credential: CredentialContext, registration_id: UUID) -> GcpRangeProjectView:
    """Re-enable only after a fresh readback of the accepted original baseline."""

    current = require_project_administrator(credential)
    with transaction.atomic():
        current = require_project_administrator(current)
        row = GcpRangeProject.objects.select_for_update().filter(pk=registration_id).first()
        if (
            row is None
            or row.status not in {"failed", "disabled"}
            or row.uses.filter(released_at__isnull=True).exists()
        ):
            raise ValidationError(_UNAVAILABLE)
        original = project_registration_input(row)
        queue_project_registration(
            row, current, original, operation="verify" if row.baseline is not None else "register"
        )
        _audit_project(row, current, "retry")
        return project_view(row)


def project_view(row: GcpRangeProject) -> GcpRangeProjectView:
    """Project the opaque registry state after the owning service has authorized it."""
    return GcpRangeProjectView(
        row.pk,
        row.organization_uuid,
        row.project_id,
        row.project_number,
        row.status,
        row.failure_code,
        row.uses.filter(released_at__isnull=True).exists(),
    )


def _audit_project(row: GcpRangeProject, current: CredentialContext, operation: str) -> None:
    """Persist administrative actor and assignment without copying provider state."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.CONFIG,
            entity_id=0,
            entity_ref=str(row.pk),
            action=AuditAction.UPDATE,
            **principal_actor_fields(current.principal),
            new_state={
                "registration_id": str(row.pk),
                "organization_uuid": str(row.organization_uuid),
                "operation": operation,
            },
            context="gcp_range_project_administration",
        ),
        strict=True,
    )
