"""Qualify immutable source and private native input before product-owner commit."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from cms.models import ParticipantControlConfiguration, RaesPackageSource, RangeInstance
from engine.services import (
    EngineError,
    PreparedNativeParticipantInput,
    fence_range_participant_power_input,
    prepare_bound_range_participant_power_input,
    prepare_range_participant_power_input,
)
from shared.authorization import TargetRef
from shared.credentials import CredentialContext
from shared.exceptions import CMSError, ValidationError
from shared.native_participant import (
    NATIVE_POWER_CONTROL_PROFILE_REF,
    NativePowerConfigurationEvidence,
    NativeRuntimeCoordinates,
)
from shared.participant_control_authority import NativeParticipantSubjectAdmission, admit_participant_subject
from shared.raes.native_power_planning import validate_bound_native_power_source
from workspaces.services import hierarchy_target_scope, resource_scope_from_ids

from ._content_authority import content_scope
from ._pack_conformance import _identity, _locked_unchanged
from ._participant_control_configuration import _configuration_digest
from ._participant_control_installation import require_native_control_policy
from ._scoped_range_lifecycle import _BINDING_FIELDS
from ._unified_authorization import require_range_action

_UNAVAILABLE = "Native participant control binding unavailable"


@contextmanager
def _binding_errors() -> Iterator[None]:
    try:
        yield
    except (ValueError, ObjectDoesNotExist, CMSError, EngineError):
        raise ValidationError(_UNAVAILABLE) from None


def _range_identity(row: RangeInstance) -> tuple[object, ...]:
    return tuple(
        getattr(row, name)
        for name in (
            *_BINDING_FIELDS,
            "uuid",
            "scenario_id",
            "event_uuid",
            "status",
            "deleted_at",
            "range_source",
            "expires_at",
            "maximum_expires_at",
        )
    )


@dataclass(frozen=True, slots=True)
class _BindingInputs:
    admission: NativeParticipantSubjectAdmission = field(repr=False)
    source: RaesPackageSource = field(repr=False)
    source_identity: tuple[str, ...] = field(repr=False)
    source_facts: tuple[object, ...] = field(repr=False)
    config: ParticipantControlConfiguration = field(repr=False)
    snapshot: RangeInstance = field(repr=False)
    native: PreparedNativeParticipantInput = field(repr=False)

    def fence(self) -> RangeInstance:
        """Caller holds one transaction; locks remain through its effect admission."""
        self.admission.fence()
        require_native_control_policy(self.config.runtime_policy_digest)
        current_source = _locked_unchanged(self.source.pk, self.source_identity)
        if (
            content_scope(current_source),
            current_source.owner_principal_uuid,
            current_source.scope_generation,
            current_source.is_operator_published,
        ) != self.source_facts:
            raise ValidationError(_UNAVAILABLE)
        current_config = ParticipantControlConfiguration.objects.select_for_update().get(pk=self.config.pk)
        current = RangeInstance.objects.select_for_update().get(pk=self.snapshot.pk)
        if (
            current_config.retired_at is not None
            or _range_identity(current) != _range_identity(self.snapshot)
            or (current.expires_at is not None and current.expires_at <= timezone.now())
        ):
            raise ValidationError(_UNAVAILABLE)
        # The request has its own custody lifecycle. Hold that row as well as
        # the CMS projection until Engine's native fence and binding commit.
        if current.request is None:
            raise ValidationError(_UNAVAILABLE)
        request = type(current.request).objects.select_for_update().get(pk=current.request_id)
        if any(
            getattr(request, name) != getattr(current, name)
            for name in ("scope_kind", "account_id", "organization_id", "workspace_id", "owner_principal_uuid")
        ):
            raise ValidationError(_UNAVAILABLE)
        fence_range_participant_power_input(self.native)
        return current


def _require_qualification(
    qualification: _BindingInputs,
    source: RaesPackageSource,
    config: ParticipantControlConfiguration,
    prepared: PreparedNativeParticipantInput,
    source_facts: tuple[object, ...],
) -> None:
    """Reuse original source qualification only while every retained fact agrees."""
    if (
        source.pk != qualification.source.pk
        or _identity(source) != qualification.source_identity
        or source_facts != qualification.source_facts
        or config.pk != qualification.config.pk
        or config.configuration_digest != qualification.config.configuration_digest
        or prepared.input != qualification.native.input
    ):
        raise ValueError(_UNAVAILABLE)


def _prepare_binding_inputs(
    credential: CredentialContext,
    *,
    product: str,
    subject_uuid: UUID,
    configuration_id: UUID,
    coordinates: NativeRuntimeCoordinates | None = None,
    qualification: _BindingInputs | None = None,
) -> _BindingInputs:
    """Qualify source and native input before the ordered product transaction."""
    from cms.scenarios.realizability import _trusted_scenario_path

    try:
        admission = admit_participant_subject(credential, product, subject_uuid)
        subject = admission.subject
        candidate = RangeInstance.objects.get(pk=subject.range_instance_pk)
        target = TargetRef("event", subject.event_uuid)
        snapshot = require_range_action(credential, candidate.uuid, "event.manage_ranges", authority_target=target)
        if snapshot.expires_at is not None and snapshot.expires_at <= timezone.now():
            raise ValueError(_UNAVAILABLE)
        if (
            snapshot.request is None
            or (coordinates is None and snapshot.status not in {"ready", "paused"})
            or snapshot.range_source != product
        ):
            raise ValueError(_UNAVAILABLE)
        scope = resource_scope_from_ids(
            kind=snapshot.scope_kind,
            account_id=snapshot.account_id,
            organization_id=snapshot.organization_id,
            workspace_id=snapshot.workspace_id,
        )
        if scope.organization_uuid is None:
            raise ValueError(_UNAVAILABLE)
        organization_scope = hierarchy_target_scope("organization", scope.organization_uuid)
        config = ParticipantControlConfiguration.objects.get(
            pk=configuration_id, organization_uuid=scope.organization_uuid, retired_at__isnull=True
        )
        installed = require_native_control_policy(config.runtime_policy_digest)
        source = RaesPackageSource.objects.get(pk=config.source_uuid, scenario_id=snapshot.scenario_id)
        source_scope = content_scope(source)
        source_facts = (
            source_scope,
            source.owner_principal_uuid,
            source.scope_generation,
            source.is_operator_published,
        )
        if source_scope != organization_scope and not (
            source_scope.kind == "installation" and source.is_operator_published
        ):
            raise ValueError(_UNAVAILABLE)
        prepared = (
            prepare_range_participant_power_input(credential, snapshot.request.request_id, authority_target=target)
            if coordinates is None
            else prepare_bound_range_participant_power_input(
                credential, snapshot.request.request_id, coordinates, authority_target=target
            )
        )
        if (
            source.package_digest != config.source_package_digest
            or source.package_digest != prepared.input.compiler.source_package_digest
        ):
            raise ValueError(_UNAVAILABLE)
        source_identity = _identity(source)
        if qualification is not None:
            _require_qualification(qualification, source, config, prepared, source_facts)
            evidence = NativePowerConfigurationEvidence(
                qualification.config.raes_version, qualification.config.implementation_digest
            )
        else:
            with _trusted_scenario_path(source) as (path, _):
                if path is None:
                    raise ValueError(_UNAVAILABLE)
                evidence = validate_bound_native_power_source(
                    path,
                    context=prepared.input.compiler.context,
                    power=prepared.input.power,
                    selection=config.selection,
                )
        if (
            config.profile_ref != NATIVE_POWER_CONTROL_PROFILE_REF
            or config.raes_version != evidence.raes_version
            or config.implementation_digest != evidence.implementation_digest
            or config.configuration_digest
            != _configuration_digest(
                config.organization_uuid,
                source.pk,
                source.package_digest,
                config.selection,
                evidence,
                installed.policy_digest,
            )
        ):
            raise ValueError(_UNAVAILABLE)
    except Exception:  # noqa: BLE001  # keep private source and native policy diagnostics local
        raise ValidationError(_UNAVAILABLE) from None

    return _BindingInputs(admission, source, source_identity, source_facts, config, snapshot, prepared)
