"""Private authenticated workload routing into the fixed persistent native owner."""

from uuid import UUID

from pydantic import SecretStr

from cms.models import ParticipantControlBinding
from engine.services import (
    authenticate_native_power_operation,
    finish_native_power_invocation,
    withdraw_native_power_invocation,
)
from shared.native_participant import NativePowerInvocationGrant

from ._participant_control_commands import load_native_control_command


def begin_native_participant_invocation(
    operation_id: UUID, member_ref: str, token: SecretStr, attempt_id: UUID
) -> NativePowerInvocationGrant:
    """Authenticate the actual Job before any private source or runtime lookup."""
    from cms.participant_control_runtime import participant_control_registry

    route = authenticate_native_power_operation(operation_id, token)
    binding = ParticipantControlBinding.objects.get(
        compiler_binding_ref=route.coordinates.binding_ref,
        resource_generation=route.coordinates.resource_generation,
        run_id=route.coordinates.run_id,
        invalidated_at__isnull=True,
    )
    command = load_native_control_command(binding.pk, route.action_id)
    with participant_control_registry().lease(command.credential, binding.pk) as owner:
        return owner.begin_invocation(route, member_ref=member_ref, token=token, attempt_id=attempt_id)


def finish_native_participant_invocation(invocation_id: UUID, attempt_id: UUID, token: SecretStr) -> None:
    """Cessation remains recordable after revocation, retirement or worker drain."""
    finish_native_power_invocation(invocation_id=invocation_id, attempt_id=attempt_id, token=token)


def withdraw_native_participant_invocation(
    operation_id: UUID,
    member_ref: str,
    attempt_id: UUID,
    token: SecretStr,
) -> None:
    withdraw_native_power_invocation(
        operation_id=operation_id, member_ref=member_ref, attempt_id=attempt_id, token=token
    )
