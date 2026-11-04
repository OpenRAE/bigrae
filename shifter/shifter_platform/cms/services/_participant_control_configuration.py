"""Organization-owned installation of fixed logical participant control mappings."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from cms.models import ParticipantControlBinding, ParticipantControlConfiguration, RaesPackageSource
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.credentials import CredentialContext, resolve_local_credential
from shared.exceptions import ValidationError
from shared.native_participant import (
    NATIVE_POWER_CONTROL_PROFILE_REF,
    NativeControlConfigurationStatus,
    NativeControlConfigurationView,
    NativePowerConfigurationEvidence,
    NativePowerControlSelection,
)
from shared.operation_authority import credential_reference_fields
from shared.operation_envelope import canonical_payload_digest
from shared.raes.native_power_planning import native_power_configuration_evidence, validate_native_power_configuration

from ._content_authority import content_scope
from ._pack_conformance import _identity, _locked_unchanged
from ._participant_control_installation import require_native_control_installation
from ._runtime_plugin_packs import _require_pack_source
from ._tenant_pack_authority import admit_tenant_pack, fence_tenant_pack

_UNAVAILABLE = "Native participant control configuration unavailable"
_CHANGED = "Native participant control configuration changed"


def _configuration_digest(
    organization_uuid: UUID,
    source_uuid: UUID,
    source_package_digest: str,
    selection: NativePowerControlSelection,
    evidence: NativePowerConfigurationEvidence,
    runtime_policy_digest: str,
) -> str:
    return canonical_payload_digest(
        {
            "profile_ref": NATIVE_POWER_CONTROL_PROFILE_REF,
            "organization_uuid": str(organization_uuid),
            "source_uuid": str(source_uuid),
            "source_package_digest": source_package_digest,
            "selection": asdict(selection),
            "raes_version": evidence.raes_version,
            "implementation_digest": evidence.implementation_digest,
            "runtime_policy_digest": runtime_policy_digest,
        }
    )


def _view(row: ParticipantControlConfiguration) -> NativeControlConfigurationView:
    return NativeControlConfigurationView(
        id=row.pk,
        organization_uuid=row.organization_uuid,
        source_uuid=row.source_uuid,
        source_package_digest=row.source_package_digest,
        configuration_digest=row.configuration_digest,
        raes_version=row.raes_version,
        structural_report_ref=row.structural_report_ref,
        runtime_policy_digest=row.runtime_policy_digest,
        selection=row.selection,
    )


def read_native_control_configuration(
    credential: CredentialContext,
    organization_uuid: UUID,
    scenario_id: str,
) -> NativeControlConfigurationStatus:
    """Read administrator-visible configuration without opening a runtime or private input."""
    admission = admit_tenant_pack(credential, organization_uuid)
    installed = require_native_control_installation()
    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
    if source is None:
        raise ValidationError(_UNAVAILABLE)
    source_scope = _require_pack_source(admission.credential, organization_uuid, source)
    identity = _identity(source)
    with transaction.atomic():
        fence_tenant_pack(admission)
        current = _locked_unchanged(source.pk, identity)
        if (
            content_scope(current),
            current.owner_principal_uuid,
            current.scope_generation,
            current.is_operator_published,
        ) != (
            source_scope,
            source.owner_principal_uuid,
            source.scope_generation,
            source.is_operator_published,
        ):
            raise ValidationError(_CHANGED)
        row = (
            ParticipantControlConfiguration.objects.select_for_update()
            .filter(
                organization_uuid=organization_uuid,
                source_uuid=source.pk,
                retired_at__isnull=True,
            )
            .first()
        )
        if row is None:
            return NativeControlConfigurationStatus(None, False)
        expected = _configuration_digest(
            organization_uuid,
            source.pk,
            current.package_digest,
            row.selection,
            native_power_configuration_evidence(),
            installed.policy_digest,
        )
        return NativeControlConfigurationStatus(_view(row), row.configuration_digest != expected)


def _source_configuration_evidence(
    source: RaesPackageSource,
    selection: NativePowerControlSelection,
) -> NativePowerConfigurationEvidence:
    """Keep private source parsing and storage failures behind one native boundary."""
    from cms.scenarios.realizability import _trusted_scenario_path

    try:
        with _trusted_scenario_path(source) as (path, _):
            if path is None:
                raise ValueError(_UNAVAILABLE)
            return validate_native_power_configuration(path, selection)
    except Exception:  # noqa: BLE001  # private source, parser and storage details stay behind the service boundary
        raise ValidationError(_UNAVAILABLE) from None


def configure_native_participant_control(
    credential: CredentialContext,
    organization_uuid: UUID,
    scenario_id: str,
    *,
    expected_package_digest: str,
    selection: NativePowerControlSelection,
) -> NativeControlConfigurationView:
    """Check source and native authority before one strictly audited installation.

    This source-structure report qualifies only this mapping. It changes no
    generic catalog conformance status and installs no executable code or Job.
    """
    admission = admit_tenant_pack(credential, organization_uuid)
    installed = require_native_control_installation()
    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
    if source is None:
        raise ValidationError(_UNAVAILABLE)
    source_scope = _require_pack_source(admission.credential, organization_uuid, source)
    if not expected_package_digest or source.package_digest != expected_package_digest:
        raise ValidationError(_CHANGED)
    if not isinstance(selection, NativePowerControlSelection):
        raise ValidationError(_UNAVAILABLE)
    identity = _identity(source)
    evidence = _source_configuration_evidence(source, selection)
    digest = _configuration_digest(
        organization_uuid, source.pk, source.package_digest, selection, evidence, installed.policy_digest
    )
    with transaction.atomic():
        fence_tenant_pack(admission)
        require_native_control_installation(installed.digest)
        current = _locked_unchanged(source.pk, identity)
        if (
            content_scope(current) != source_scope
            or current.owner_principal_uuid != source.owner_principal_uuid
            or current.scope_generation != source.scope_generation
            or current.is_operator_published != source.is_operator_published
            or resolve_local_credential(admission.credential) != admission.credential
        ):
            raise ValidationError(_CHANGED)
        existing = (
            ParticipantControlConfiguration.objects.select_for_update()
            .filter(organization_uuid=organization_uuid, source_uuid=source.pk, retired_at__isnull=True)
            .first()
        )
        if existing is not None and existing.configuration_digest == digest:
            if (
                existing.profile_ref != NATIVE_POWER_CONTROL_PROFILE_REF
                or existing.selection != selection
                or existing.raes_version != evidence.raes_version
                or existing.implementation_digest != evidence.implementation_digest
                or existing.source_package_digest != source.package_digest
                or existing.runtime_policy_digest != installed.policy_digest
            ):
                raise ValidationError(_CHANGED)
            return _view(existing)
        if existing is not None:
            if ParticipantControlBinding.objects.filter(configuration=existing, invalidated_at__isnull=True).exists():
                raise ValidationError("Deactivate current participant control bindings before changing configuration")
            existing.retired_at = timezone.now()
            existing.save(update_fields=["retired_at"])
        row = ParticipantControlConfiguration.objects.create(
            organization_uuid=organization_uuid,
            source_uuid=source.pk,
            source_package_digest=source.package_digest,
            configuration_digest=digest,
            raes_version=evidence.raes_version,
            implementation_digest=evidence.implementation_digest,
            runtime_policy_digest=installed.policy_digest,
            structural_report_ref="urn:shifter:participant-control-source-check:" + str(uuid4()),
            **asdict(selection),
            **credential_reference_fields(admission.credential),
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                entity_id=0,
                entity_ref=str(source.pk),
                action=AuditAction.UPDATE,
                **principal_actor_fields(admission.credential.principal),
                new_state={
                    "participant_control_configuration": str(row.pk),
                    "organization_uuid": str(organization_uuid),
                    "configuration_digest": digest,
                    "structural_report_ref": row.structural_report_ref,
                },
            ),
            strict=True,
        )
        return _view(row)
