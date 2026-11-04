"""Current native authority and locked correlation for participant operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

if TYPE_CHECKING:
    from engine.models import ParticipantPowerReservation, ProvisionerLaunchIntent, Range
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext

_UNAVAILABLE = "Native participant operation unavailable"


@dataclass(frozen=True, slots=True)
class PreparedNativeParticipantOperation:
    """Invocation-local authority, evaluated before product and native row locks."""

    credential: CredentialContext = field(repr=False)
    action_id: UUID
    control_cut_digest: str = field(repr=False)
    _range_pk: int
    _reservation_pk: int
    _authority: tuple[tuple[str, object], ...] = field(repr=False)


def prepare_native_participant_operation(
    credential: CredentialContext,
    action_id: UUID,
    control_cut_digest: str,
    *,
    authority_target: TargetRef | None = None,
) -> PreparedNativeParticipantOperation:
    """Admit native remote policy once before the caller's ordered transaction."""
    from engine.models import ParticipantPowerReservation, Range

    from ._launch_authority import admit_launch_authority

    if not isinstance(action_id, UUID):
        raise ValueError(_UNAVAILABLE)
    retained = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action_id)
    original = retained.launch_intent
    baseline = Range.objects.get(compiler_input_bindings__pk=retained.compiler_binding_id)
    authority = admit_launch_authority(
        original.payload,
        credential,
        authority_action="event.manage_ranges" if authority_target is not None else None,
        authority_target=authority_target,
    )
    return PreparedNativeParticipantOperation(
        credential, action_id, control_cut_digest, baseline.pk, retained.pk, tuple(authority.items())
    )


@contextmanager
def locked_native_participant_operation(
    credential: CredentialContext,
    action_id: UUID,
    control_cut_digest: str,
    *,
    authority_target: TargetRef | None = None,
    prepared: PreparedNativeParticipantOperation | None = None,
) -> Iterator[tuple[Range, ParticipantPowerReservation, ProvisionerLaunchIntent]]:
    """Resolve remote policy before locks; retain the native fence through commit."""
    if prepared is None:
        prepared = prepare_native_participant_operation(
            credential, action_id, control_cut_digest, authority_target=authority_target
        )
    else:
        fields = dict(prepared._authority)
        if (
            prepared.credential != credential
            or prepared.action_id != action_id
            or prepared.control_cut_digest != control_cut_digest
            or fields.get("authority_target_type")
            != (authority_target.type if authority_target is not None else "range")
            or (authority_target is not None and fields.get("authority_target_uuid") != authority_target.uuid)
        ):
            raise ValueError(_UNAVAILABLE)
    with locked_prepared_native_participant_operation(prepared) as result:
        yield result


@contextmanager
def locked_prepared_native_participant_operation(
    prepared: PreparedNativeParticipantOperation,
) -> Iterator[tuple[Range, ParticipantPowerReservation, ProvisionerLaunchIntent]]:
    """Use the already evaluated authority; perform only local commit fences."""
    from engine.launch_intents import assert_provisioner_input_matches
    from engine.models import ParticipantPowerReservation, ProvisionerLaunchIntent, RaesCompilerInputBinding, Range
    from shared.credentials import resolve_local_credential

    from ._compiled_participants import _scope_digest
    from ._launch_authority import (
        assert_admitted_launch_binding,
        assert_launch_authority_replay,
    )

    if not isinstance(prepared, PreparedNativeParticipantOperation):
        raise ValueError(_UNAVAILABLE)
    credential, control_cut_digest = prepared.credential, prepared.control_cut_digest
    authority = dict(prepared._authority)
    with transaction.atomic():
        row = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=prepared._range_pk)
        assert_admitted_launch_binding(authority, row)
        if resolve_local_credential(credential) != credential:
            raise ValueError(_UNAVAILABLE)
        reservation = ParticipantPowerReservation.objects.select_for_update().get(pk=prepared._reservation_pk)
        intent = ProvisionerLaunchIntent.objects.select_for_update().get(pk=reservation.launch_intent_id)
        assert_launch_authority_replay(intent, authority)
        binding = RaesCompilerInputBinding.objects.only("range_id", "resource_generation", "scope_digest").get(
            pk=reservation.compiler_binding_id
        )
        if (
            reservation.action_id != prepared.action_id
            or binding.range_id != row.pk
            or reservation.fenced_at is not None
            or row.provisioner_operation_id != intent.operation_id
            or binding.resource_generation != row.resource_generation
            or binding.scope_digest != _scope_digest(row)
            or not control_cut_digest
            or reservation.control_cut_digest != control_cut_digest
        ):
            raise ValueError(_UNAVAILABLE)
        assert_provisioner_input_matches(intent.payload, intent.operation_id)
        yield row, reservation, intent
