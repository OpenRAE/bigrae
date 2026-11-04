"""Native original requests and operation references beside the SDK's owned history."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, cast
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction

from cms.models import ParticipantControlBinding, ParticipantControlCommand
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.exceptions import ValidationError
from shared.native_participant import (
    NativeControlCommandKind,
    NativeControlCommandRecord,
    NativeControlSubmission,
    NativePreparedControlRequest,
)
from shared.operation_authority import credential_reference_fields, credential_reference_from_record
from shared.raes.native_request_binding import validate_prepared_native_power_request

from ._participant_control_binding import PreparedNativeControlBinding

_UNAVAILABLE = "Native participant request unavailable"
MAX_NATIVE_CONTROL_COMMANDS = 256


@contextmanager
def _command_errors() -> Iterator[None]:
    try:
        yield
    except (ValueError, IntegrityError, ObjectDoesNotExist):
        raise ValidationError(_UNAVAILABLE) from None


def _record(row: ParticipantControlCommand) -> NativeControlCommandRecord:
    return NativeControlCommandRecord(
        id=row.pk,
        binding_id=row.binding_id,
        kind=cast(NativeControlCommandKind, row.kind),
        verb=cast(Literal["pause", "resume"], row.verb),
        proposal_id=row.proposal_uuid,
        action_id=row.action_uuid,
        request=NativePreparedControlRequest(bytes(row.request_json), bytes(row.subject_json), row.control_cut_digest),
        credential=credential_reference_from_record(row),
        portable_operation_id=row.portable_operation_uuid,
    )


def persist_native_control_command(
    admission: PreparedNativeControlBinding,
    *,
    request_id: UUID,
    kind: NativeControlCommandKind,
    verb: Literal["pause", "resume"],
    proposal_id: UUID,
    action_id: UUID,
    request: NativePreparedControlRequest,
) -> NativeControlCommandRecord:
    """Strictly audit one original request before any call into the runtime owner.

    Only the fixed native worker supplies these prepared carriers. HTTP callers
    supply native identities and choices, never request bytes or SDK verdicts.
    A duplicate retains its exact body and original proof; it cannot rebase.
    """
    credential = admission._inputs.admission.credential
    # This installed implementation declares human-supervised control. Service
    # principals may request and consume reviewed work; they cannot supply the
    # human approval that this selected mode requires. Native event policy and
    # credential ceilings remain mandatory for every actor and command.
    if kind == "approval" and credential.principal.kind != "human":
        raise ValidationError("Human approval required for this participant control profile")
    with transaction.atomic(), _command_errors():
        admission.fence()
        commands = ParticipantControlCommand.objects.filter(binding_id=admission.view.id)
        decisions = frozenset(
            commands.filter(proposal_uuid=proposal_id, kind__in=["approval", "denial"]).values_list("pk", flat=True)
        )
        validate_prepared_native_power_request(
            request,
            coordinates=admission.view.coordinates,
            selection=admission.configuration.selection,
            allowed_decision_ids=decisions,
            submission=NativeControlSubmission(
                request_id=request_id,
                kind=kind,
                verb=verb,
                proposal_id=proposal_id,
                action_id=action_id,
                expected_cut_digest=getattr(request, "control_cut_digest", ""),
            ),
        )
        existing = commands.select_for_update().filter(pk=request_id).first()
        if existing is not None:
            record = _record(existing)
            if (record.kind, record.verb, record.proposal_id, record.action_id, record.request, record.credential) != (
                kind,
                verb,
                proposal_id,
                action_id,
                request,
                credential,
            ):
                raise ValidationError(_UNAVAILABLE)
            return record
        if commands.count() >= MAX_NATIVE_CONTROL_COMMANDS:
            raise ValidationError("Native participant request limit reached")
        if kind != "proposal":
            proposal = commands.get(pk=proposal_id, kind="proposal")
            if proposal.action_uuid != action_id or proposal.verb != verb:
                raise ValidationError(_UNAVAILABLE)
        elif ParticipantControlCommand.objects.filter(kind="proposal", action_uuid=action_id).exists():
            raise ValidationError(_UNAVAILABLE)
        row = ParticipantControlCommand.objects.create(
            id=request_id,
            binding_id=admission.view.id,
            kind=kind,
            verb=verb,
            proposal_uuid=proposal_id,
            action_uuid=action_id,
            request_json=request.intent_json,
            subject_json=request.subject_json,
            control_cut_digest=request.control_cut_digest,
            **credential_reference_fields(credential),
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=admission._inputs.snapshot.pk,
                entity_ref=str(admission.view.range_uuid),
                action=AuditAction.CREATE,
                **principal_actor_fields(credential.principal),
                request_id=str(admission.request_id),
                new_state={
                    "participant_control_command": str(row.pk),
                    "binding_ref": str(admission.view.id),
                    "command_kind": kind,
                    "proposal_ref": str(proposal_id),
                    "action_ref": str(action_id),
                    "requested_control_cut": request.control_cut_digest,
                },
            ),
            strict=True,
        )
        return _record(row)


def load_native_control_command(binding_id: UUID, command_id: UUID) -> NativeControlCommandRecord:
    """Private fixed-owner lookup; product HTTP reads must authorize independently."""
    with _command_errors():
        return _record(ParticipantControlCommand.objects.get(pk=command_id, binding_id=binding_id))


def native_control_command_catalog(binding_id: UUID) -> tuple[NativeControlCommandRecord, ...]:
    """Read a bounded immutable request catalog, never infer current permission from it."""
    rows = list(ParticipantControlCommand.objects.filter(binding_id=binding_id).order_by("created_at", "pk")[:257])
    if len(rows) > MAX_NATIVE_CONTROL_COMMANDS:
        raise ValidationError(_UNAVAILABLE)
    with _command_errors():
        return tuple(_record(row) for row in rows)


def correlate_native_control_operation(
    binding_id: UUID, command_id: UUID, portable_operation_id: UUID
) -> NativeControlCommandRecord:
    """Record the fixed owner's observed SDK receipt once, without effect authority.

    The owner verifies its public SDK operation before calling this private
    seam. A client cannot supply a receipt. Revoked proof does not erase an
    already observed operation; dispatch and invocation still reauthorize it.
    """
    if not isinstance(portable_operation_id, UUID) or not portable_operation_id.int:
        raise ValidationError(_UNAVAILABLE)
    with transaction.atomic(), _command_errors():
        binding = ParticipantControlBinding.objects.select_for_update().get(pk=binding_id)
        row = ParticipantControlCommand.objects.select_for_update().get(pk=command_id, binding_id=binding_id)
        if row.portable_operation_uuid is not None:
            if row.portable_operation_uuid != portable_operation_id:
                raise ValidationError(_UNAVAILABLE)
            return _record(row)
        row.portable_operation_uuid = portable_operation_id
        row.save(update_fields=["portable_operation_uuid"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=0,
                entity_ref=str(binding.range_uuid),
                action=AuditAction.UPDATE,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                request_id=str(command_id),
                new_state={
                    "participant_control_command": str(command_id),
                    "portable_operation_ref": str(portable_operation_id),
                    "initiating_principal_ref": str(row.initiating_principal_uuid),
                },
            ),
            strict=True,
        )
        return _record(row)
