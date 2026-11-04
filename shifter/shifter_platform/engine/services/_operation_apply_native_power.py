"""Apply native member observations against the exact retained operation input."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.audit import AuditEntityType
from shared.operation_envelope import OperationEnvelopeError, validate_operation_envelope
from shared.operation_results import OperationResultError, ResultStep, parse_result_payload
from shared.raes.power_input import NativePowerInput, build_native_power_input, parse_native_power_input

from ._operation_apply_effects import _audit

if TYPE_CHECKING:
    from engine.models import OperationInput, OperationResultInbox, Range


_MEMBER_STEPS = frozenset(
    {
        ResultStep.RANGE_RAES_MEMBERS_PAUSED,
        ResultStep.RANGE_RAES_MEMBERS_RESUMING,
        ResultStep.RANGE_RAES_MEMBERS_READY,
    }
)
_TERMINAL_STEPS = frozenset({ResultStep.RANGE_TERMINAL_PAUSED, ResultStep.RANGE_TERMINAL_READY})


def _require_envelope_identity(
    row: OperationResultInbox,
    stored: OperationInput,
    envelope: dict[str, Any],
) -> None:
    """Input and result envelopes validate their own versions and share operation identity."""
    for key in ("operation_id", "request_id", "resource", "operation", "contract_version"):
        if str(getattr(stored, key)) != str(envelope[key]):
            raise OperationResultError("Native power operation identity changed")
    # Input v2 binds launch authority; the existing result writer independently
    # emits supported v1 envelopes. Their operation identity must agree, while
    # each envelope retains its own already validated transport version.
    for key in ("operation_id", "request_id", "resource", "operation"):
        if str(getattr(row, key)) != str(envelope[key]):
            raise OperationResultError("Native power operation identity changed")


def _bound_input(row: OperationResultInbox, target: Range) -> NativePowerInput:
    """Revalidate current incarnation, inventory and immutable operation identity."""
    from engine.models import OperationInput, ParticipantPowerReservation

    if ParticipantPowerReservation.objects.filter(
        launch_intent__operation_id=row.operation_id,
        fenced_at__isnull=False,
    ).exists():
        raise OperationResultError("Native power operation was fenced during recovery")
    stored = OperationInput.objects.filter(operation_id=row.operation_id).first()
    if stored is None or row.resource != "range":
        raise OperationResultError("Native power operation input is unavailable")
    try:
        envelope = validate_operation_envelope(stored.envelope)
    except OperationEnvelopeError:
        raise OperationResultError("Native power operation input is invalid") from None
    _require_envelope_identity(row, stored, envelope)
    payload = envelope["payload"]
    if payload.get("range_spec") != target.range_config:
        raise OperationResultError("Native power plan changed")
    from ._common import EngineError
    from ._native_participant_origin import native_power_origin

    try:
        origin = native_power_origin(target)
    except EngineError:
        raise OperationResultError("Native power provisioning origin unavailable") from None
    if payload.get("native_provisioning_operation_id") != str(origin):
        raise OperationResultError("Native power provisioning origin changed")
    admitted = parse_native_power_input(payload.get("native_power"), plan=target.range_config)
    current = parse_native_power_input(
        build_native_power_input(
            target.range_config,
            target.provisioned_instances,
            target.resource_generation,
            backend=str(target.range_backend or ""),
        ),
        plan=target.range_config,
    )
    if admitted.resource_generation != current.resource_generation or (
        {member.member_ref: (member.target, member.incarnation) for member in admitted.members}
        != {member.member_ref: (member.target, member.incarnation) for member in current.members}
    ):
        raise OperationResultError("Native power resource binding changed")
    return admitted


def apply_native_power_result(
    row: OperationResultInbox,
    step: ResultStep,
    payload: dict[str, Any],
    target: Range,
) -> str | None:
    """Apply member readback, or verify terminal settlement for the caller.

    A terminal return of None means the existing lifecycle writer may settle
    the range. All validation precedes writes and the caller holds its lock.
    """
    admitted = _bound_input(row, target)
    if step in _TERMINAL_STEPS:
        _verify_terminal(row, payload, admitted)
        return None
    if step not in _MEMBER_STEPS:
        raise OperationResultError("Native power result step is unsupported")
    observed = _validated_observations(payload, admitted)
    members = target.provisioned_instances
    if not isinstance(members, list):
        raise OperationResultError("Native power realization is unavailable")
    previous = {member["uuid"]: member.get("status") for member in members if member["uuid"] in observed}
    target.provisioned_instances = [
        {**member, "status": observed[member["uuid"]]} if member["uuid"] in observed else member for member in members
    ]
    target.save(update_fields=["provisioned_instances", "updated_at"])
    _audit(
        AuditEntityType.RANGE,
        target.pk,
        next(iter(observed.values())),
        request_id=str(row.request_id),
        previous={"members": previous},
        detail={"members": observed, "resource_generation": str(admitted.resource_generation)},
    )
    return f"{len(observed)} native member(s)"


def _validated_observations(payload: dict[str, Any], admitted: NativePowerInput) -> dict[str, str]:
    """Validate the resource epoch and bounded observed subset before any write."""
    if payload["resource_generation"] != str(admitted.resource_generation):
        raise OperationResultError("Native power readback resource generation changed")
    observed = {member["member_ref"]: member["status"] for member in payload["members"]}
    if not set(observed) <= {member.member_ref for member in admitted.members}:
        raise OperationResultError("Native power readback names an unbound member")
    return observed


def _verify_terminal(row: OperationResultInbox, payload: dict[str, Any], admitted: NativePowerInput) -> None:
    """A terminal assertion cannot replace this operation's complete member evidence."""
    from engine.models import OperationResultDisposition, OperationResultInbox, ParticipantPowerReservation

    reservation = ParticipantPowerReservation.objects.filter(
        launch_intent__operation_id=row.operation_id,
        released_at__isnull=False,
        compiler_binding__resource_generation=admitted.resource_generation,
    ).first()
    if reservation is None:
        raise OperationResultError("Native power terminal lacks released native admission")
    invocations = list(
        reservation.participantpowerinvocation_set.values_list("member_ref", "closed_at", "permission_issued")
    )
    if {reference for reference, _, _ in invocations} != {member.member_ref for member in admitted.members} or any(
        closed_at is None or not issued for _, closed_at, issued in invocations
    ):
        raise OperationResultError("Native power terminal lacks completed invocation readback")

    step = ResultStep.RANGE_RAES_MEMBERS_PAUSED if row.operation == "pause" else ResultStep.RANGE_RAES_MEMBERS_READY
    evidence = OperationResultInbox.objects.filter(
        operation_id=row.operation_id,
        request_id=row.request_id,
        resource=row.resource,
        operation=row.operation,
        result_step=step,
        disposition=OperationResultDisposition.APPLIED,
    ).first()
    if evidence is None:
        raise OperationResultError("Native power terminal lacks member readback")
    observed_payload = parse_result_payload(
        row.resource, row.operation, step=step, payload=evidence.envelope["payload"]
    )
    observed = _validated_observations(observed_payload, admitted)
    if set(observed) != {member.member_ref for member in admitted.members} or set(observed.values()) != {
        payload["status"]
    }:
        raise OperationResultError("Native power terminal lacks complete matching readback")
