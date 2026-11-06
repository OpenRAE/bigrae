"""Tenant administration over verified catalog packs and Engine plugin bindings."""

from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q

from cms.exceptions import CMSError
from cms.models import RaesPackageSource
from cms.scenarios.catalog_presentation import list_catalog_presentations
from cms.scenarios.realizability import _availability_provider, _trusted_scenario_path
from engine.services import (
    RuntimePluginPackView,
    bind_runtime_plugin,
    list_runtime_plugin_bindings,
    prepare_runtime_plugin_binding,
    project_parameters_for_binding,
    runtime_plugin_plan_parameters,
)
from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log, principal_actor_fields
from shared.authorization import TargetRef
from shared.credentials import CredentialContext, resolve_credential_scope, resolve_current_credential
from shared.exceptions import ValidationError
from shared.identity_scope import ResourceScope
from shared.raes.pack_conformance import validate_pack_contract
from shared.raes.project_parameters import required_project_parameters, select_project_parameters
from shared.raes.realizability import RealizabilityOutcome, assess_scenario_capability
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginScope
from workspaces.services import OrganizationAuthorizationError

from ._content_authority import content_scope, require_content_scope

_ORGANIZATION_DENIED = "Organization access denied"
_PACK_UNAVAILABLE = "The pack is unavailable"
_PACK_CHANGED = "The pack changed; reload its current version before saving"


def _require_pack_source(user: CredentialContext, organization_uuid: UUID, source: RaesPackageSource) -> ResourceScope:
    """Private custody or current operator publication must match the authorized view."""
    scope = resolve_credential_scope(TargetRef("organization", organization_uuid))
    try:
        actual = content_scope(source)
        require_content_scope(user, scope, "read_content")
    except CMSError:
        raise OrganizationAuthorizationError(_ORGANIZATION_DENIED) from None
    if actual != scope and not (actual.kind == "installation" and source.is_operator_published):
        raise ValidationError(_PACK_UNAVAILABLE)
    return actual


def list_runtime_plugin_packs(user: CredentialContext, organization_uuid: UUID) -> list[dict[str, Any]]:
    """List verified packs visible to an authorized organization administrator."""
    try:
        user = resolve_current_credential(user)
    except ValueError:
        raise OrganizationAuthorizationError(_ORGANIZATION_DENIED) from None
    scope = resolve_credential_scope(TargetRef("organization", organization_uuid))
    bindings = {row.pack_id: row for row in list_runtime_plugin_bindings(user, organization_uuid)}
    available = dict(
        RaesPackageSource.objects.filter(
            Q(organization_uuid=organization_uuid) | Q(organization_uuid__isnull=True),
        ).values_list("scenario_id", "organization_uuid")
    )
    packs = []
    try:
        entries = list_catalog_presentations(user=user, scope=scope)
    except CMSError:
        raise OrganizationAuthorizationError(_ORGANIZATION_DENIED) from None
    for entry in entries:
        if entry["id"] not in available:
            continue
        evidence = entry.get("raes")
        if evidence is None:
            continue
        binding = bindings.get(entry["id"])
        packs.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "pack_digest": evidence["package_digest"],
                "can_update": available[entry["id"]] == organization_uuid,
                "binding": asdict(binding) if binding is not None else None,
            }
        )
    return sorted(packs, key=lambda row: row["id"])


def runtime_plugin_pack_detail(user: CredentialContext, organization_uuid: UUID, pack_id: str) -> dict[str, Any]:
    """Return selectable guest identities only; never apply a compiled plan."""
    return _pack_detail(user, organization_uuid, pack_id)


def _pack_detail(
    user: CredentialContext,
    organization_uuid: UUID,
    pack_id: str,
    *,
    bindings: PluginTargetBindings | None = None,
    report: str = "",
) -> dict[str, Any]:
    """A pending template exposes no guest choices until a real project is selected."""
    entry = next((row for row in list_runtime_plugin_packs(user, organization_uuid) if row["id"] == pack_id), None)
    if entry is None:
        raise ValidationError(_PACK_UNAVAILABLE)
    source = RaesPackageSource.objects.filter(scenario_id=pack_id).first()
    if source is None:
        raise ValidationError(_PACK_UNAVAILABLE)
    _require_pack_source(user, organization_uuid, source)
    with _trusted_scenario_path(source) as (path, _gap):
        if path is None:
            raise ValidationError("The registered pack could not be verified; reinstall the pack before binding")
        parameters = None
        try:
            required = required_project_parameters(path)
        except ValueError:
            raise ValidationError("The pack requires unsupported runtime parameters") from None
        if required:
            scope = RuntimePluginScope(
                organization_uuid=organization_uuid, pack_id=pack_id, pack_digest=source.package_digest
            )
            if bindings is None:
                try:
                    _, facts = runtime_plugin_plan_parameters(scope)
                except ValidationError:
                    facts = {}
                if not facts:
                    return {**entry, "pack_digest": source.package_digest, "targets": []}
            else:
                facts = project_parameters_for_binding(scope, bindings)
                if not facts:
                    raise ValidationError("Select a ready registered target project for this pack")
            parameters = select_project_parameters(path, facts)
        if report:
            try:
                validate_pack_contract(path, report, parameters=parameters)
            except Exception:  # noqa: BLE001  # untrusted planner errors can contain private source values
                raise ValidationError("The pack failed validation with the selected project") from None
        assessment = assess_scenario_capability(
            path, parameters=parameters, artifact_availability_provider=_availability_provider("gce")
        )
    if assessment.outcome == RealizabilityOutcome.INDETERMINATE:
        raise ValidationError("The pack's guest targets could not be resolved")
    # Bind to the exact source row whose bytes were verified, not an earlier list
    # projection if catalog registration changed while it was being loaded.
    entry["pack_digest"] = source.package_digest
    return {
        **entry,
        "targets": [{"address": row.address, "os_family": row.os_family} for row in assessment.image_demands],
    }


def set_runtime_plugin_pack(
    user: CredentialContext,
    organization_uuid: UUID,
    pack_id: str,
    payload: dict[str, Any],
    *,
    audit: RequestAudit | None = None,
) -> RuntimePluginPackView:
    """Bind a verified pack revision to an administrator-selected installation."""
    detail = runtime_plugin_pack_detail(user, organization_uuid, pack_id)
    if payload["pack_digest"] != detail["pack_digest"]:
        raise ValidationError(_PACK_CHANGED)
    try:
        bindings = PluginTargetBindings.model_validate(payload["bindings"])
    except ValueError:
        raise ValidationError("Select a pack guest for every required plugin target") from None
    snapshot = RaesPackageSource.objects.filter(scenario_id=pack_id).first()
    if snapshot is None:
        raise ValidationError(_PACK_UNAVAILABLE)
    source_scope = _require_pack_source(user, organization_uuid, snapshot)
    if snapshot.conformance_status == "pending" and snapshot.organization_uuid != organization_uuid:
        raise ValidationError("The pack owner must complete conformance validation")
    plugin_scope = RuntimePluginScope(
        organization_uuid=organization_uuid, pack_digest=detail["pack_digest"], pack_id=pack_id
    )
    admission = prepare_runtime_plugin_binding(
        user, plugin_scope, payload["installation_id"], bindings.model_dump(mode="json"), enabled=payload["enabled"]
    )
    report = "urn:shifter:pack-conformance:" + str(uuid4())
    configured = _pack_detail(user, organization_uuid, pack_id, bindings=bindings, report=report)
    if configured["pack_digest"] != detail["pack_digest"]:
        raise ValidationError(_PACK_CHANGED)
    if not set(bindings.targets.values()) <= {row["address"] for row in configured["targets"]}:
        raise ValidationError("Select a pack guest for every required plugin target")
    from ._runtime_file_admission import fence_file_selection, prepare_file_selection

    tenant_scope = resolve_credential_scope(TargetRef("organization", organization_uuid))
    files = prepare_file_selection(user, tenant_scope, bindings.file_assets, assignment=True)
    with transaction.atomic():
        source = RaesPackageSource.objects.select_for_update().filter(scenario_id=pack_id).first()
        try:
            locked_scope = content_scope(source)
        except CMSError:
            raise ValidationError(_PACK_CHANGED) from None
        if (
            source is None
            or source.package_digest != detail["pack_digest"]
            or source.owner_principal_uuid != snapshot.owner_principal_uuid
            or source.scope_generation != snapshot.scope_generation
            or source.is_operator_published != snapshot.is_operator_published
            or locked_scope != source_scope
        ):
            raise ValidationError(_PACK_CHANGED)
        fence_file_selection(user, tenant_scope, files, assignment=True)
        result = bind_runtime_plugin(
            admission,
            plugin_scope,
            payload["installation_id"],
            bindings.model_dump(mode="json"),
            enabled=payload["enabled"],
            audit=audit,
        )
        if source.conformance_status == "pending":
            source.conformance_status = "passed"
            source.conformance_report_ref = report
            source.save(update_fields=["conformance_status", "conformance_report_ref", "updated_at"])
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.SCENARIO,
                    entity_id=0,
                    entity_ref=pack_id,
                    action=AuditAction.UPDATE,
                    **principal_actor_fields(user.principal),
                    new_state={
                        "package_digest": source.package_digest,
                        "conformance_status": source.conformance_status,
                        "conformance_report_ref": report,
                    },
                ),
                strict=True,
            )
        return result
