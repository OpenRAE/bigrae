"""Principal NGFW effects retain native interpretation, operation inputs and audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from engine.interpreter import interpret
from engine.models import Instance, Range, Request
from engine.services._device_authority import (
    admitted_device_authority,
    assert_device_creation,
    prepare_device_authority,
    prepare_ngfw_creation,
)
from engine.services._launch.intents import _enqueue_admitted_provisioner_launch
from engine.services._launch_authority.authority import assert_admitted_launch_binding
from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.credentials import CredentialContext
from shared.schemas.range import InstanceSpec

if TYPE_CHECKING:
    from uuid import UUID

    from engine.services._device_authority import PreparedDeviceCreation
    from shared.identity_scope import ResourceScope
    from shared.schemas import RequestSpec


PreparedDeviceLifecycle = tuple[int, str, tuple[tuple[str, Any], ...], CredentialContext, dict[str, Any]]


def create_principal_ngfw(
    request_spec: RequestSpec,
    credential: CredentialContext,
    scope: ResourceScope,
    prepared: PreparedDeviceCreation | None,
) -> UUID:
    """Create and queue the native device with original principal custody."""

    prepared = prepared or prepare_ngfw_creation(request_spec, credential, scope)

    if (
        len(request_spec.items) != 1
        or not isinstance(request_spec.items[0], InstanceSpec)
        or request_spec.items[0].role != "ngfw"
        or request_spec.items[0].ngfw_app is None
        or not request_spec.items[0].ngfw_app.is_hydrated
    ):
        raise ValueError("Device specification unavailable")
    with transaction.atomic():
        assert_device_creation(prepared, request_spec, credential, scope)
        existing = Request.objects.filter(request_id=request_spec.request_id).first()
        if existing is not None:
            raise ValueError("Device creation already recorded")
        request = interpret(request_spec, principal=credential.principal, resource_scope=scope)
        runtime = Instance.objects.select_related("request").get(request=request, role="ngfw")
        runtime.status = "provisioning"
        runtime.save(update_fields=["status", "updated_at"])
        runtime.apps.update(status="provisioning")
        authority = admitted_device_authority(runtime, credential)
        payload = {"version": 1, "resource": "ngfw", "operation": "provision", "request_id": str(request.request_id)}
        identifier = _enqueue_admitted_provisioner_launch(
            ["ngfw", "provision", "--request-id", str(request.request_id)], payload, authority
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.NGFW,
                entity_id=runtime.pk,
                entity_ref=str(authority["authority_resource_uuid"]),
                action="provision",
                **principal_actor_fields(credential.principal),
                request_id=str(request.request_id),
                new_state={"status": "provisioning", "launch_intent": identifier},
            ),
            strict=True,
        )
        return request.request_id


def prepare_ngfw_lifecycle(request_id: UUID, credential: CredentialContext, operation: str) -> PreparedDeviceLifecycle:
    """Admit one device transition before taking lifecycle row locks."""

    if operation not in {"deprovision", "start", "stop"}:
        raise ValueError("Device operation unavailable")
    runtime = Instance.objects.select_related("request").get(request__request_id=request_id, role="ngfw")
    if (
        operation == "deprovision"
        and Range.objects.filter(ngfw_instance=runtime).exclude(status__in=["failed", "destroyed"]).exists()
    ):
        raise ValueError("Device still has attached ranges")
    payload = {"version": 1, "resource": "ngfw", "operation": operation, "request_id": str(request_id)}
    fields = prepare_device_authority(payload, credential)
    if not fields:
        raise PermissionError("Device authority unavailable")
    return (runtime.pk, runtime.status, tuple(fields.items()), credential, payload)


def commit_ngfw_lifecycle(prepared: PreparedDeviceLifecycle) -> bool:
    """Fence native device state and atomically queue the admitted transition."""

    native_id, status, authority, credential, payload = prepared
    fields = dict(authority)
    operation = payload["operation"]
    with transaction.atomic():
        runtime = Instance.objects.select_for_update(of=("self",)).select_related("request").get(pk=native_id)
        assert_admitted_launch_binding(fields, runtime)
        if runtime.request is None:
            raise ValueError("Device request unavailable")
        if runtime.status != status:
            raise ValueError("Device state changed")
        allowed = {
            "deprovision": {"ready", "paused", "failed", "destroying"},
            "start": {"paused", "failed"},
            "stop": {"ready"},
        }
        if status not in allowed[operation]:
            raise ValueError("Device state unavailable")
        if operation == "deprovision":
            if Range.objects.filter(ngfw_instance=runtime).exclude(status__in=["failed", "destroyed"]).exists():
                raise ValueError("Device still has attached ranges")
            runtime.status = "destroying"
            runtime.save(update_fields=["status", "updated_at"])
            runtime.apps.update(status="destroying")
        identifier = _enqueue_admitted_provisioner_launch(
            ["ngfw", operation, "--request-id", str(runtime.request.request_id)], payload, fields
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.NGFW,
                entity_id=runtime.pk,
                entity_ref=str(fields["authority_resource_uuid"]),
                action={"start": "resume", "stop": "pause", "deprovision": "deprovision"}[operation],
                **principal_actor_fields(credential.principal),
                request_id=str(runtime.request.request_id),
                new_state={"launch_intent": identifier},
            ),
            strict=True,
        )
    return True
