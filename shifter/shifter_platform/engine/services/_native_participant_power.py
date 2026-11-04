"""Held native power work for the installed participant-runtime callback.

This is an owning-service seam, not an HTTP admission surface. The installed
CMS controller must establish the product-to-controller mapping before calling
it. Native range authority, custody, generation, footprint and audit remain
mandatory here, independently of portable policy admission.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.native_participant import NativeParticipantPowerAction
from shared.operation_envelope import canonical_payload_digest
from shared.raes.power_input import build_native_power_input, planned_member_references

if TYPE_CHECKING:
    from engine.models import RaesCompilerInputBinding, Range
    from shared.authorization import TargetRef
    from shared.credentials import CredentialContext

    from ._native_participant_binding import PreparedNativeParticipantOperation

_UNAVAILABLE = "Native participant operation unavailable"


@dataclass(frozen=True, slots=True)
class PreparedNativePowerReservation:
    """Invocation-local native admission; product owners fence before committing."""

    request_id: UUID
    action: NativeParticipantPowerAction = field(repr=False)
    _credential: CredentialContext = field(repr=False)
    _authority: tuple[tuple[str, object], ...] = field(repr=False)


def _meaning_digest(action: NativeParticipantPowerAction) -> str:
    """Commit native correlation without retaining SDK state or private content."""
    payload = asdict(action)
    payload["coordinates"] = {key: str(value) for key, value in asdict(action.coordinates).items()}
    return canonical_payload_digest(payload)


def _require_action_binding(row: Range, action: NativeParticipantPowerAction) -> RaesCompilerInputBinding:
    from engine.models import RaesCompilerInputBinding

    from ._compiled_participants import _scope_digest

    if not isinstance(action, NativeParticipantPowerAction) or action.verb not in {"pause", "resume"}:
        raise ValueError(_UNAVAILABLE)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", action.control_cut_digest):
        raise ValueError(_UNAVAILABLE)
    if any(
        not isinstance(value, str) or not 0 < len(value) <= 256
        for value in (
            action.participant_address,
            action.controller_address,
            action.episode_id,
            action.action_contract_address,
            action.observation_boundary_address,
        )
    ):
        raise ValueError(_UNAVAILABLE)
    if row.resource_generation != action.coordinates.resource_generation or row.ngfw_instance_id is not None:
        raise ValueError(_UNAVAILABLE)
    binding = (
        RaesCompilerInputBinding.objects.only("id", "participant_references", "compiler_input_digest")
        .filter(
            range=row,
            binding_ref=action.coordinates.binding_ref,
            resource_generation=row.resource_generation,
            scope_digest=_scope_digest(row),
        )
        .first()
    )
    if binding is None or binding.compiler_input_digest != action.compiler_input_digest:
        raise ValueError(_UNAVAILABLE)
    participants = {entry["participant_ref"]: entry for entry in binding.participant_references}
    if action.participant_address not in participants or action.controller_address not in participants:
        raise ValueError(_UNAVAILABLE)
    # Native power covers the entire compiled compute footprint, including
    # every realized member count. It cannot conceal a larger affected range.
    members = planned_member_references(row.range_config)
    targets = tuple(sorted({member.rsplit("#", 1)[0] for member in members}))
    if action.target_addresses != targets or not set(targets) <= set(
        participants[action.participant_address]["scope_refs"]
    ):
        raise ValueError(_UNAVAILABLE)
    build_native_power_input(
        row.range_config,
        row.provisioned_instances,
        resource_generation=row.resource_generation,
        backend=str(row.range_backend or ""),
    )
    return binding


def reserve_native_participant_power(
    credential: CredentialContext,
    request_id: UUID,
    action: NativeParticipantPowerAction,
    *,
    authority_target: TargetRef | None = None,
) -> UUID:
    """Authorize and audit held work; nothing can dispatch it at this stage."""
    return commit_native_participant_power(
        prepare_native_participant_power(credential, request_id, action, authority_target=authority_target)
    )


def prepare_native_participant_power(
    credential: CredentialContext,
    request_id: UUID,
    action: NativeParticipantPowerAction,
    *,
    authority_target: TargetRef | None = None,
) -> PreparedNativePowerReservation:
    """Admit remote native policy before CTF/CMS acquire their owning SQL locks."""
    from ._launch_authority import admit_launch_authority

    if not isinstance(action, NativeParticipantPowerAction) or action.verb not in {"pause", "resume"}:
        raise ValueError(_UNAVAILABLE)
    if any(
        not UUID(value).int or str(UUID(value)) != value
        for value in (action.action_id, action.proposal_ref, action.approval_ref)
    ):
        raise ValueError(_UNAVAILABLE)
    payload = {"version": 1, "resource": "range", "operation": action.verb, "request_id": str(request_id)}
    authority = admit_launch_authority(
        payload,
        credential,
        authority_action="event.manage_ranges" if authority_target is not None else None,
        authority_target=authority_target,
    )
    return PreparedNativePowerReservation(request_id, action, credential, tuple(authority.items()))


def commit_native_participant_power(prepared: PreparedNativePowerReservation) -> UUID:
    """Commit unchanged prepared authority inside the product's ordered fence."""
    from engine.launch_intents import _enqueue_admitted_provisioner_launch
    from engine.models import ParticipantPowerReservation, ProvisionerLaunchIntent, Range

    from ._launch_authority import assert_admitted_launch_binding

    if not isinstance(prepared, PreparedNativePowerReservation):
        raise ValueError(_UNAVAILABLE)
    credential, request_id, action = prepared._credential, prepared.request_id, prepared.action
    authority = dict(prepared._authority)
    action_id, proposal_id = UUID(action.action_id), UUID(action.proposal_ref)
    payload = {"version": 1, "resource": "range", "operation": action.verb, "request_id": str(request_id)}
    meaning_digest = _meaning_digest(action)
    with transaction.atomic():
        row = Range.objects.select_for_update().select_related("request").get(request__request_id=request_id)
        assert_admitted_launch_binding(authority, row)
        binding = _require_action_binding(row, action)
        existing = (
            ParticipantPowerReservation.objects.select_related("launch_intent").filter(action_id=action_id).first()
        )
        if existing is not None:
            if (
                existing.fenced_at is not None
                or existing.meaning_digest != meaning_digest
                or existing.compiler_binding_id != binding.pk
            ):
                raise ValueError(_UNAVAILABLE)
            return existing.launch_intent.operation_id
        required, pending = ("ready", "pausing") if action.verb == "pause" else ("paused", "resuming")
        from engine.models import ParticipantPowerInvocation

        if (
            row.status not in {required, "failed"}
            or ParticipantPowerInvocation.objects.filter(
                reservation__compiler_binding__range=row,
                closed_at__isnull=True,
            ).exists()
        ):
            raise ValueError(_UNAVAILABLE)
        previous_status = row.status
        row.status = pending
        row.save(update_fields=["status", "updated_at"])
        intent_id = _enqueue_admitted_provisioner_launch(
            ["range", action.verb, "--request-id", str(request_id)],
            payload,
            authority,
            hold_for_participant=True,
        )
        intent = ProvisionerLaunchIntent.objects.get(intent_id=intent_id)
        if intent.status != "HELD":
            raise ValueError(_UNAVAILABLE)
        reservation = ParticipantPowerReservation.objects.create(
            launch_intent=intent,
            compiler_binding=binding,
            run_id=action.coordinates.run_id,
            participant_address=action.participant_address,
            controller_address=action.controller_address,
            episode_id=action.episode_id,
            action_id=action_id,
            proposal_id=proposal_id,
            approval_uuid=UUID(action.approval_ref),
            meaning_digest=meaning_digest,
            previous_status=previous_status,
            control_cut_digest=action.control_cut_digest,
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action=action.verb,
                **principal_actor_fields(credential.principal),
                request_id=str(request_id),
                new_state={
                    "status": pending,
                    "dispatch": "held",
                    "participant_reservation": str(reservation.pk),
                    "action_id": str(action_id),
                    "run_id": str(action.coordinates.run_id),
                    "resource_generation": str(row.resource_generation),
                },
            ),
            strict=True,
        )
        return intent.operation_id


def record_native_participant_admission(
    credential: CredentialContext,
    action_id: UUID,
    *,
    portable_operation_uuid: UUID,
    control_cut_digest: str,
    authority_target: TargetRef | None = None,
    admission: PreparedNativeParticipantOperation | None = None,
) -> None:
    """Correlate a successful SDK call at its captured cut, retaining the hold.

    The installed owner supplies the receipt from its exact public action call
    and computes the current cut before allowing another SDK mutation. This
    private service seam accepts no caller-supplied portable receipt over HTTP.
    It grants no dispatch or provider invocation authority.
    """
    from ._native_participant_binding import locked_native_participant_operation

    if not isinstance(portable_operation_uuid, UUID):
        raise ValueError(_UNAVAILABLE)
    with locked_native_participant_operation(
        credential,
        action_id,
        control_cut_digest,
        authority_target=authority_target,
        prepared=admission,
    ) as (row, reservation, intent):
        if reservation.portable_operation_uuid is not None:
            if reservation.portable_operation_uuid != portable_operation_uuid:
                raise ValueError(_UNAVAILABLE)
            return
        if intent.status != "HELD":
            raise ValueError(_UNAVAILABLE)
        reservation.portable_operation_uuid = portable_operation_uuid
        reservation.save(update_fields=["portable_operation_uuid"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                **principal_actor_fields(credential.principal),
                request_id=str(intent.payload["request_id"]),
                new_state={
                    "participant_admission": "committed",
                    "dispatch": "held",
                    "action_id": str(action_id),
                    "portable_operation_ref": str(portable_operation_uuid),
                },
            ),
            strict=True,
        )
