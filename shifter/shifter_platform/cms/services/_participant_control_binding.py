"""Bind current native product custody to exact compiler and physical generation."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from django.db import transaction

from cms.models import ParticipantControlBinding
from engine.services import (
    BoundNativeParticipantInput,
    PreparedNativeParticipantInput,
)
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.authorization import TargetRef
from shared.credentials import CredentialContext
from shared.exceptions import ValidationError
from shared.native_participant import (
    NativeControlBindingView,
    NativeControlConfigurationView,
    NativeRuntimeCoordinates,
)
from shared.operation_authority import credential_reference_fields

from ._participant_control_configuration import _view as configuration_view
from ._participant_control_input import _binding_errors, _BindingInputs, _prepare_binding_inputs

_UNAVAILABLE = "Native participant control binding unavailable"


def _view(row: ParticipantControlBinding) -> NativeControlBindingView:
    return NativeControlBindingView(
        row.pk,
        row.configuration_id,
        row.range_uuid,
        row.product,
        row.product_subject_uuid,
        NativeRuntimeCoordinates(row.compiler_binding_ref, row.resource_generation, row.run_id),
    )


def bind_native_participant_control(
    credential: CredentialContext, *, product: str, subject_uuid: UUID, configuration_id: UUID
) -> NativeControlBindingView:
    """Allocate routing identity under exact native fences, without runtime authority."""
    inputs = _prepare_binding_inputs(
        credential, product=product, subject_uuid=subject_uuid, configuration_id=configuration_id
    )
    config, native = inputs.config, inputs.native.input
    with transaction.atomic(), _binding_errors():
        current = inputs.fence()
        request = current.request
        if request is None:
            raise ValidationError(_UNAVAILABLE)
        expected = {
            "configuration_id": config.pk,
            "configuration_digest": config.configuration_digest,
            "compiler_binding_ref": native.compiler.binding_ref,
            "resource_generation": native.compiler.resource_generation,
            "product": product,
            "product_subject_uuid": subject_uuid,
        }
        existing = (
            ParticipantControlBinding.objects.select_for_update()
            .filter(range_uuid=current.uuid, invalidated_at__isnull=True)
            .first()
        )
        if existing is not None:
            if any(getattr(existing, name) != value for name, value in expected.items()):
                raise ValidationError(_UNAVAILABLE)
            return _view(existing)
        row = ParticipantControlBinding.objects.create(
            range_uuid=current.uuid, **expected, **credential_reference_fields(credential)
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=current.pk,
                entity_ref=str(current.uuid),
                action=AuditAction.UPDATE,
                **principal_actor_fields(credential.principal),
                request_id=str(request.request_id),
                new_state={
                    "participant_control_binding": str(row.pk),
                    "run_id": str(row.run_id),
                    "configuration_digest": row.configuration_digest,
                    "resource_generation": str(row.resource_generation),
                },
            ),
            strict=True,
        )
        return _view(row)


@dataclass(frozen=True, slots=True)
class PreparedNativeControlBinding:
    """Private owner input and invocation-local product/CMS/native fence."""

    view: NativeControlBindingView
    _inputs: _BindingInputs = field(repr=False)

    @property
    def native(self) -> PreparedNativeParticipantInput:
        """Retain original private compilation and generation, never an HTTP view."""
        return self._inputs.native

    @property
    def configuration(self) -> NativeControlConfigurationView:
        """Project the admitted native installation's logical selection."""
        return configuration_view(self._inputs.config)

    @property
    def request_id(self) -> UUID:
        """Select the current owning native request, never one supplied by a Job."""
        request = self._inputs.snapshot.request
        if request is None:
            raise ValidationError(_UNAVAILABLE)
        return request.request_id

    @property
    def authority_target(self) -> TargetRef:
        """Retain the actual product event as the native authority target."""
        return TargetRef("event", self._inputs.admission.subject.event_uuid)

    @contextmanager
    def source_path(self) -> Iterator[Path]:
        """Keep verified object-pack staging alive only through owner construction."""
        from cms.scenarios.realizability import _trusted_scenario_path

        with _trusted_scenario_path(self._inputs.source) as (path, _):
            if path is None:
                raise ValidationError(_UNAVAILABLE)
            yield path

    def fence(self) -> BoundNativeParticipantInput:
        """Fence this exact active binding inside the caller's native transaction."""
        with _binding_errors():
            current = self._inputs.fence()
            row = ParticipantControlBinding.objects.select_for_update().get(pk=self.view.id)
            if (
                row.invalidated_at is not None
                or _view(row) != self.view
                or row.range_uuid != current.uuid
                or row.configuration_digest != self._inputs.config.configuration_digest
            ):
                raise ValidationError(_UNAVAILABLE)
            return self.native.input


def prepare_native_control_binding(
    credential: CredentialContext,
    binding_id: UUID,
    *,
    qualification: PreparedNativeControlBinding | None = None,
) -> PreparedNativeControlBinding:
    """Reopen the same run during pending work without admitting a replacement run."""
    with _binding_errors():
        row = ParticipantControlBinding.objects.get(pk=binding_id, invalidated_at__isnull=True)
        view = _view(row)
        if qualification is not None and qualification.view != view:
            raise ValidationError(_UNAVAILABLE)
        inputs = _prepare_binding_inputs(
            credential,
            product=row.product,
            subject_uuid=row.product_subject_uuid,
            configuration_id=row.configuration_id,
            coordinates=view.coordinates,
            qualification=qualification._inputs if qualification is not None else None,
        )
        if inputs.snapshot.uuid != row.range_uuid or inputs.config.configuration_digest != row.configuration_digest:
            raise ValidationError(_UNAVAILABLE)
        return PreparedNativeControlBinding(view, inputs)
