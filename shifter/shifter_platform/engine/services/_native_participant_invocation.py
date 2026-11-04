"""One-use native call admission under current runtime and workload authority.

Only the serialized runtime owner calls this private seam at its live cut.
The returned identifier is consumed before publication. A lost response cannot
be retried into a second permission, and no grant expires into another call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import SecretStr

from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields
from shared.native_participant import (
    NativePowerInvocationGrant,
    NativePowerInvocationRoute,
    NativeRuntimeCoordinates,
    native_power_invocation_id,
)

from ._native_participant_binding import (
    PreparedNativeParticipantOperation,
    locked_prepared_native_participant_operation,
    prepare_native_participant_operation,
)

if TYPE_CHECKING:
    from engine.models import ParticipantPowerReservation
    from shared.cloud.kubernetes.workload_identity import VerifiedTaskWorkload

from shared.native_power_protocol import NATIVE_POWER_TOKEN_AUDIENCE as _NATIVE_AUDIENCE

_UNAVAILABLE = "Native participant invocation unavailable"


@dataclass(frozen=True, slots=True)
class PreparedNativePowerInvocation:
    """Verified worker and native proof before the product's SQL fence."""

    operation: PreparedNativeParticipantOperation = field(repr=False)
    member_ref: str
    worker: VerifiedTaskWorkload = field(repr=False)
    attempt_id: UUID


def authenticate_native_power_operation(operation_id: UUID, token: SecretStr) -> NativePowerInvocationRoute:
    """Verify the actual Job before the worker opens private source/runtime input."""
    from engine.models import ParticipantPowerReservation, RaesCompilerInputBinding

    try:
        reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(
            launch_intent__operation_id=operation_id
        )
        _authenticate_worker(reservation, token)
        if reservation.approval_uuid is None:
            raise ValueError(_UNAVAILABLE)
        binding = RaesCompilerInputBinding.objects.only("binding_ref", "resource_generation").get(
            pk=reservation.compiler_binding_id
        )
        return NativePowerInvocationRoute(
            reservation.action_id,
            operation_id,
            reservation.approval_uuid,
            NativeRuntimeCoordinates(binding.binding_ref, binding.resource_generation, reservation.run_id),
        )
    except Exception:  # noqa: BLE001  # no operation existence, workload details or provider faults leave this boundary
        raise ValueError(_UNAVAILABLE) from None


def native_participant_power_unresolved(coordinates: NativeRuntimeCoordinates) -> bool:
    """Private serialized-owner exclusion, not an authorization or effect verdict."""
    from engine.models import ParticipantPowerInvocation

    return ParticipantPowerInvocation.objects.filter(
        reservation__compiler_binding__binding_ref=coordinates.binding_ref,
        reservation__compiler_binding__resource_generation=coordinates.resource_generation,
        reservation__run_id=coordinates.run_id,
        closed_at__isnull=True,
    ).exists()


def _authenticate_worker(
    reservation: ParticipantPowerReservation, token: SecretStr, *, for_completion: bool = False
) -> VerifiedTaskWorkload:
    """Establish the live workload, independently of initiating-user permission."""
    from engine.ecs._workload import assert_provisioner_workload
    from engine.launch_intents import command_from_payload
    from shared.cloud import get_task_runner
    from shared.cloud.exceptions import CloudTaskError
    from shared.cloud.kubernetes import KubernetesTaskRunner

    intent = reservation.launch_intent
    if (
        (not for_completion and reservation.approval_uuid is None)
        or reservation.released_at is None
        or reservation.portable_operation_uuid is None
        or intent.status != "SUCCEEDED"
    ):
        raise ValueError(_UNAVAILABLE)
    command = command_from_payload({**intent.payload, "operation_id": str(intent.operation_id)})
    if not for_completion:
        assert_provisioner_workload(intent.executing_workload, command, str(intent.intent_id))
    expected = intent.executing_workload
    if not expected.get("service_account_name"):
        raise ValueError(_UNAVAILABLE)
    runner = get_task_runner()
    if not isinstance(runner, KubernetesTaskRunner):
        raise ValueError(_UNAVAILABLE)
    try:
        worker = runner.authenticate_task_workload(
            cluster=expected["namespace"],
            task_ref=intent.task_ref,
            expected_identity=expected,
            token=token,
            audience=_NATIVE_AUDIENCE,
        )
    except CloudTaskError:
        raise ValueError(_UNAVAILABLE) from None
    if for_completion:
        # A deployment change cannot confer another permission, but it must
        # not prevent the original verified Pod from recording cessation.
        # Authenticate its immutable admitted workload against the retained
        # input rather than accepting a modified launch-identity row.
        from engine.models import OperationInput

        from ._launch_authority import assert_input_authority_binding

        stored = OperationInput.objects.get(operation_id=intent.operation_id)
        assert_input_authority_binding(stored, intent)
    return worker


def begin_native_power_invocation(
    *,
    action_id: UUID,
    member_ref: str,
    control_cut_digest: str,
    token: SecretStr,
    attempt_id: UUID,
) -> NativePowerInvocationGrant:
    """Authenticate the live Job, then consume an exact native call under locks."""
    return begin_prepared_native_power_invocation(
        prepare_native_power_invocation(
            action_id=action_id,
            member_ref=member_ref,
            control_cut_digest=control_cut_digest,
            token=token,
            attempt_id=attempt_id,
        )
    )


def prepare_native_power_invocation(
    *, action_id: UUID, member_ref: str, control_cut_digest: str, token: SecretStr, attempt_id: UUID
) -> PreparedNativePowerInvocation:
    """Authenticate Kubernetes and admit remote policy before product row locks."""
    from engine.models import ParticipantPowerReservation
    from shared.authorization import TargetRef
    from shared.operation_authority import credential_reference_from_record

    if not isinstance(attempt_id, UUID) or not attempt_id.int:
        raise ValueError(_UNAVAILABLE)
    reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action_id)
    intent = reservation.launch_intent
    worker = _authenticate_worker(reservation, token)
    credential = credential_reference_from_record(intent)
    target = TargetRef("event", intent.authority_target_uuid) if intent.authority_target_type == "event" else None
    operation = prepare_native_participant_operation(credential, action_id, control_cut_digest, authority_target=target)
    return PreparedNativePowerInvocation(operation, member_ref, worker, attempt_id)


def begin_prepared_native_power_invocation(prepared: PreparedNativePowerInvocation) -> NativePowerInvocationGrant:
    """Consume once under the owning product transaction without remote I/O."""
    from engine.models import ParticipantPowerInvocation
    from shared.raes.power_input import build_native_power_input, parse_native_power_input

    if not isinstance(prepared, PreparedNativePowerInvocation):
        raise ValueError(_UNAVAILABLE)
    credential = prepared.operation.credential
    member_ref, worker = prepared.member_ref, prepared.worker
    with locked_prepared_native_participant_operation(prepared.operation) as (row, current, launch):
        if (
            launch.status != "SUCCEEDED"
            or current.released_at is None
            or row.status != {"pause": "pausing", "resume": "resuming"}.get(launch.payload["operation"])
            or ParticipantPowerInvocation.objects.filter(
                reservation__compiler_binding__range=row, closed_at__isnull=True
            ).exists()
            or ParticipantPowerInvocation.objects.filter(reservation=current, member_ref=member_ref).exists()
        ):
            raise ValueError(_UNAVAILABLE)
        power = parse_native_power_input(
            build_native_power_input(
                row.range_config,
                row.provisioned_instances,
                row.resource_generation,
                backend=str(row.range_backend or ""),
            ),
            plan=row.range_config,
        )
        members = [member for member in power.members if member.member_ref == member_ref]
        if len(members) != 1:
            raise ValueError(_UNAVAILABLE)
        previous = ParticipantPowerInvocation.objects.filter(reservation=current).first()
        if previous is not None and (previous.pod_uid, previous.job_uid, previous.container_id) != (
            worker.pod_uid,
            worker.job_uid,
            worker.container_id,
        ):
            raise ValueError(_UNAVAILABLE)
        invocation = ParticipantPowerInvocation.objects.create(
            invocation_id=native_power_invocation_id(launch.operation_id, member_ref),
            reservation=current,
            member_ref=member_ref,
            pod_uid=worker.pod_uid,
            job_uid=worker.job_uid,
            pod_name=worker.pod_name,
            container_id=worker.container_id,
            attempt_id=prepared.attempt_id,
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                **principal_actor_fields(credential.principal),
                request_id=str(launch.payload["request_id"]),
                new_state={
                    "native_invocation": str(invocation.pk),
                    "operation_id": str(launch.operation_id),
                    "pod_uid": worker.pod_uid,
                    "job_uid": worker.job_uid,
                },
            ),
            strict=True,
        )
        member = members[0]
        return NativePowerInvocationGrant(
            invocation_id=invocation.pk,
            operation_id=launch.operation_id,
            resource_generation=power.resource_generation,
            verb="pause" if launch.payload["operation"] == "pause" else "resume",
            member_ref=member_ref,
            target=member.target,
            incarnation=member.incarnation,
            attempt_id=invocation.attempt_id,
        )


def finish_native_power_invocation(*, invocation_id: UUID, attempt_id: UUID, token: SecretStr) -> None:
    """Record this verified worker's cessation, without granting another call.

    Only the installed worker invokes this after its bounded helper returns.
    This is native permission bookkeeping, not world-effect/readiness evidence.
    Revoked initiating authority does not prevent recording cessation.
    """
    from django.db import transaction
    from django.utils import timezone

    from engine.models import ParticipantPowerInvocation, RaesCompilerInputBinding, Range
    from shared.operation_authority import credential_reference_from_record

    retained = ParticipantPowerInvocation.objects.select_related("reservation__launch_intent").get(pk=invocation_id)
    worker = _authenticate_worker(retained.reservation, token, for_completion=True)
    range_pk = RaesCompilerInputBinding.objects.values_list("range_id", flat=True).get(
        pk=retained.reservation.compiler_binding_id
    )
    with transaction.atomic():
        row = Range.objects.select_for_update().get(pk=range_pk)
        invocation = ParticipantPowerInvocation.objects.select_for_update().get(pk=invocation_id)
        if (invocation.pod_uid, invocation.job_uid, invocation.container_id, invocation.attempt_id) != (
            worker.pod_uid,
            worker.job_uid,
            worker.container_id,
            attempt_id,
        ):
            raise ValueError(_UNAVAILABLE)
        if invocation.closed_at is not None:
            return
        invocation.closed_at = timezone.now()
        invocation.save(update_fields=["closed_at"])
        launch = retained.reservation.launch_intent
        credential = credential_reference_from_record(launch)
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=row.pk,
                entity_ref=str(row.cms_range_uuid),
                action="update",
                **principal_actor_fields(credential.principal),
                request_id=str(launch.payload["request_id"]),
                new_state={
                    "native_invocation": str(invocation.pk),
                    "permission_closed": True,
                    "operation_id": str(launch.operation_id),
                    "pod_uid": worker.pod_uid,
                    "job_uid": worker.job_uid,
                },
            ),
            strict=True,
        )
