"""Native RAES creation validates explicit customer scope and independent ownership."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from engine.ecs._config import _get_engine_task_config
from engine.models import ProvisionerLaunchIntent, Range
from engine.services._common import _persist_task_arn
from engine.services._launch.intents import _enqueue_admitted_provisioner_launch
from engine.services._launch_authority.authority import admitted_range_authority_fields, prepare_launch_authority
from engine.services._raes.range_bindings import PreparedRaesRangeCreation as PreparedRaesRangeCreation
from engine.services._raes.range_bindings import RaesRangeRef
from engine.services._range.authority import project_range_authority
from engine.services._range.creation_origin import (
    _RANGE_CREATION_AUTHORITY_UNAVAILABLE,
    _assert_creation_origin,
    _installation_creation_authority,
)
from management.services import human_principal_user_id
from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.authorization import AuthorizationRequest
from shared.authorization.policy import require_authorization, scope_parent
from shared.credentials import resolve_current_credential, resolve_local_credential
from shared.operation_authority import credential_reference_from_fields
from shared.operation_envelope import canonical_payload_digest
from workspaces.services import resolve_range_scope_binding

if TYPE_CHECKING:
    from typing import Any
    from uuid import UUID

    from engine.services._raes.range_bindings import RangeBindings
    from engine.services._range.authority import RangeAuthorityProjection
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext
    from shared.identity_scope import PrincipalRef, ResourceScope


_CREATION_ADMISSION_CHANGED = "Range creation admission changed"


def prepare_raes_range_creation(
    bindings: RangeBindings, workspace_id: int | None, user_id: int | None, compiled_plan: dict[str, Any]
) -> PreparedRaesRangeCreation:
    """Freeze parent admission and the compiled plan before native creation."""
    fields = prepare_principal_range_fields(bindings, workspace_id, user_id)
    return PreparedRaesRangeCreation(
        bindings, workspace_id, user_id, canonical_payload_digest(compiled_plan), tuple(fields.items())
    )


def prepared_creation_fields(
    prepared: PreparedRaesRangeCreation | None,
    bindings: RangeBindings,
    workspace_id: int | None,
    user_id: int | None,
    compiled_plan: dict[str, Any],
) -> dict[str, Any]:
    """Validate prepared custody and plan identity before replaying creation fields."""
    if not isinstance(prepared, PreparedRaesRangeCreation):
        raise ValueError(_CREATION_ADMISSION_CHANGED)
    if (prepared.workspace_id, prepared.user_id) != (workspace_id, user_id) or (
        prepared.plan_digest != canonical_payload_digest(compiled_plan)
    ):
        raise ValueError(_CREATION_ADMISSION_CHANGED)
    if _creation_binding_facts(prepared.bindings) != _creation_binding_facts(bindings):
        raise ValueError(_CREATION_ADMISSION_CHANGED)
    return dict(prepared.fields)


def _creation_binding_facts(bindings: RangeBindings) -> tuple[object, ...]:
    """Compare the exact proof, owner, scope and parent retained by preparation."""
    return (
        bindings.credential,
        bindings.resource_scope,
        bindings.cms_range_uuid,
        bindings.owner_principal,
        bindings.authority_action,
        bindings.authority_target,
    )


def admitted_creation_authority(prepared: PreparedRaesRangeCreation, runtime: Range) -> dict[str, object]:
    """Fence the prepared parent before atomically queuing the new generation."""

    bindings = prepared.bindings
    if bindings.credential is None or runtime.request is None or not isinstance(runtime.range_config, dict):
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    fields = prepared_creation_fields(prepared, bindings, runtime.workspace_id, runtime.user_id, runtime.range_config)
    scope = assert_principal_range_creation(bindings, fields)
    if any(getattr(runtime, name) != value for name, value in fields.items()):
        raise ValueError("Range creation custody changed")
    if scope.kind == "installation":
        return _installation_creation_authority(bindings.credential, runtime)
    projection = project_range_authority(runtime.request.request_id)
    if projection.scope != scope:
        raise ValueError("Range creation projections changed")
    parent = _creation_parent(bindings, projection)
    action = bindings.authority_action or f"{parent.type}.launch_range"
    target = bindings.authority_target or parent
    return admitted_range_authority_fields(bindings.credential, projection, runtime, action=action, target=target)


def _creation_parent(bindings: RangeBindings, projection: RangeAuthorityProjection) -> TargetRef:
    """Match the separately authorized event parent or exact customer ancestry."""
    target = bindings.authority_target
    parent = target if target is not None and target.type == "event" else scope_parent(projection.scope)
    if parent != projection.parent:
        raise ValueError("Range creation parent changed")
    return parent


def prepare_principal_range_fields(
    bindings: RangeBindings, workspace_id: int | None, user_id: int | None
) -> dict[str, object]:
    """Evaluate parent policy before the create transaction; never borrow a user."""

    if _get_engine_task_config() is None:
        raise ValueError("Range provisioner unavailable")
    scope = bindings.resource_scope
    if bindings.credential is None:
        raise ValueError("Range creation credential unavailable")
    current = resolve_current_credential(bindings.credential)
    if scope is None or not isinstance(bindings.cms_range_uuid, UUID):
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    if not bindings.cms_range_uuid.int:
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    owner = bindings.owner_principal or current.principal
    scope_fields = _creation_scope_fields(bindings, current, workspace_id, user_id)
    parent = scope_parent(scope)
    action = bindings.authority_action or f"{parent.type}.launch_range"
    target = bindings.authority_target or parent
    require_authorization(AuthorizationRequest(current.principal, action, target, scope, current.ceiling))
    if resolve_current_credential(current) != current:
        raise ValueError("Range authority changed")
    return {
        "owner_principal_uuid": owner.uuid,
        "cms_range_uuid": bindings.cms_range_uuid,
        **scope_fields,
        "event_uuid": _creation_event_uuid(bindings),
    }


def _creation_scope_fields(
    bindings: RangeBindings, current: CredentialContext, workspace_id: int | None, user_id: int | None
) -> dict[str, object]:
    """Resolve installation custody or customer membership before policy admission."""

    scope = bindings.resource_scope
    if scope is None:
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    if scope.kind == "installation":
        if current.principal.kind != "service" or user_id is not None or workspace_id is not None:
            raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
        resolved = resolve_range_scope_binding(scope)
    else:
        _assert_historical_user(bindings.owner_principal or current.principal, user_id)
        resolved = (
            resolve_range_scope_binding(scope)
            if bindings.authority_target is not None
            else resolve_range_scope_binding(scope, member=current.principal)
        )
    if resolved.workspace_id != workspace_id:
        raise ValueError("Range scope conflicts")
    return {"scope_kind": resolved.kind, "account_id": resolved.account_id, "organization_id": resolved.organization_id}


def _creation_event_uuid(bindings: RangeBindings) -> UUID | None:
    """Return only an explicitly admitted event parent, never inferred ownership."""
    target = bindings.authority_target
    return target.uuid if target is not None and target.type == "event" else None


def _assert_historical_user(owner: PrincipalRef, user_id: int | None) -> None:
    """Human attribution cannot substitute for the admitted principal owner."""

    expected_user = human_principal_user_id(owner) if owner.kind == "human" else None
    if expected_user != user_id:
        raise ValueError("Range historical attribution conflicts")


def assert_principal_range_creation(bindings: RangeBindings, fields: dict[str, object]) -> ResourceScope:
    """Only fresh scalar ancestry/membership/credential checks run under SQL locks."""

    if bindings.credential is None or bindings.resource_scope is None:
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    current = resolve_local_credential(bindings.credential)
    owner = bindings.owner_principal or current.principal
    resolved = (
        resolve_range_scope_binding(bindings.resource_scope)
        if bindings.resource_scope.kind == "installation" or bindings.authority_target is not None
        else resolve_range_scope_binding(bindings.resource_scope, member=current.principal, for_update=True)
    )
    actual = (current, owner.uuid, resolved.kind, resolved.account_id, resolved.organization_id)
    expected = (
        bindings.credential,
        fields["owner_principal_uuid"],
        fields["scope_kind"],
        fields["account_id"],
        fields["organization_id"],
    )
    if actual != expected or (bindings.resource_scope.kind == "installation" and current.principal.kind != "service"):
        raise ValueError("Range scope changed")
    return bindings.resource_scope


def verify_principal_range_replay(
    existing: Range, fields: dict[str, object], bindings: RangeBindings, compiled_plan: dict[str, Any]
) -> None:
    """Refuse replay that changes immutable range custody or compiled input."""
    if existing.owner_principal_uuid is None:
        if fields:
            raise ValueError("Range ownership conflict")
        return
    if bindings.credential is None:
        raise ValueError("Range creation credential unavailable")
    _assert_replayed_custody(existing, fields)
    if existing.range_config != compiled_plan:
        raise ValueError("Range plan conflict")
    _assert_creation_origin(existing, bindings.credential)


def _assert_replayed_custody(existing: Range, fields: Mapping[str, object]) -> None:
    """A replay must preserve every server-recorded owner and ancestry scalar."""
    if not fields or any(getattr(existing, name) != value for name, value in fields.items()):
        raise ValueError("Range ownership conflict")


def dispatch_principal_raes_range(
    runtime: Range, credential: CredentialContext, prepared: PreparedRaesRangeCreation | None
) -> RaesRangeRef:
    """Admission precedes locks; native queue and strict audit commit together."""

    if runtime.request is None:
        raise ValueError("Range request unavailable")
    request_id = runtime.request.request_id
    command = ["raes-range", "provision", "--request-id", str(request_id)]
    payload = {"version": 1, "resource": "raes-range", "operation": "provision", "request_id": str(request_id)}
    if prepared is not None and prepared.bindings.credential != credential:
        raise PermissionError("Range creation authority changed")
    authority = prepare_launch_authority(payload, credential) if prepared is None else None
    with transaction.atomic():
        _lock_creation_ancestry(prepared)
        runtime = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=runtime.pk)
        if runtime.request is None or runtime.request.request_id != request_id:
            raise ValueError("Range creation origin changed")
        _assert_creation_origin(runtime, credential)
        authority = _fence_dispatch_authority(prepared, runtime, credential, authority)

        _assert_creation_origin(runtime, credential_reference_from_fields(authority))
        identifier = _enqueue_admitted_provisioner_launch(command, payload, authority)
        intent = ProvisionerLaunchIntent.objects.get(intent_id=identifier)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=runtime.pk,
                entity_ref=str(runtime.cms_range_uuid),
                action="provision",
                **principal_actor_fields(credential.principal),
                request_id=str(request_id),
                new_state={"status": runtime.status, "launch_intent": identifier},
            ),
            strict=True,
        )

        _persist_task_arn(runtime, "provision", intent.task_ref or f"local-pending:{identifier}")
    return RaesRangeRef(str(request_id), str(runtime.uuid), runtime.status, True)


def _lock_creation_ancestry(prepared: PreparedRaesRangeCreation | None) -> None:
    """Lock prepared ancestry before Range; revalidate its exact facts after both locks."""
    if prepared is None:
        return

    scope = prepared.bindings.resource_scope
    if scope is None:
        raise ValueError(_RANGE_CREATION_AUTHORITY_UNAVAILABLE)
    resolve_range_scope_binding(scope, for_update=True)


def _fence_dispatch_authority(
    prepared: PreparedRaesRangeCreation | None,
    runtime: Range,
    credential: CredentialContext,
    authority: dict[str, object] | None,
) -> dict[str, object]:
    """Retain current local proof and exact prepared ancestry before durable enqueue."""
    if resolve_local_credential(credential) != credential:
        raise PermissionError("Range creation authority changed")
    if prepared is not None:
        # Local facts only: policy admission precedes the owning transaction.
        authority = admitted_creation_authority(prepared, runtime)
    if authority is None:
        raise PermissionError("Range creation authority unavailable")
    return authority
