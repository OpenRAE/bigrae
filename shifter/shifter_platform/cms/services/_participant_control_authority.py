"""Recheck original native proofs independently of runtime and transport identity."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from engine.services import BoundNativeParticipantInput
from shared.native_participant import NativeControlCommandRecord

from ._participant_control_binding import PreparedNativeControlBinding, prepare_native_control_binding
from ._participant_control_commands import load_native_control_command

_UNAVAILABLE = "Native participant authority unavailable"


@contextmanager
def _authority_errors() -> Iterator[None]:
    try:
        yield
    except Exception:  # noqa: BLE001  # native permission and private compilation diagnostics remain private
        raise ValueError(_UNAVAILABLE) from None


@dataclass(frozen=True, slots=True)
class PreparedNativeControlCommand:
    """Invocation-local product, source, custody and original credential fences."""

    command: NativeControlCommandRecord = field(repr=False)
    binding: PreparedNativeControlBinding = field(repr=False)

    def fence(self) -> BoundNativeParticipantInput:
        """Caller holds a transaction; retain the native locks through admission."""
        with _authority_errors():
            from cms.models import ParticipantControlCommand

            native = self.binding.fence()
            if (
                ParticipantControlCommand.objects.select_for_update().get(pk=self.command.id).dispatch_fenced_at
                is not None
            ):
                raise ValueError(_UNAVAILABLE)
            return native


def prepare_native_control_command(
    binding_id: UUID,
    command_id: UUID,
    *,
    qualification: PreparedNativeControlBinding | None = None,
) -> PreparedNativeControlCommand:
    """Evaluate current policy using the immutable original command's proof."""
    with _authority_errors():
        command = load_native_control_command(binding_id, command_id)
        binding = prepare_native_control_binding(command.credential, binding_id, qualification=qualification)
        if command.kind == "approval" and command.credential.principal.kind != "human":
            raise ValueError(_UNAVAILABLE)
        return PreparedNativeControlCommand(command, binding)


@dataclass(frozen=True, slots=True)
class PreparedNativeReviewedAction:
    """Three original proofs; the SDK separately establishes accepted review meaning."""

    action: PreparedNativeControlCommand = field(repr=False)
    proposal: PreparedNativeControlCommand = field(repr=False)
    approval: PreparedNativeControlCommand = field(repr=False)

    def fence(self) -> BoundNativeParticipantInput:
        """Fence requester, reviewer and consumer before admitting a physical effect."""
        with _authority_errors():
            proposed = self.proposal.fence()
            reviewed = self.approval.fence()
            consumed = self.action.fence()
            if proposed != reviewed or consumed != reviewed:
                raise ValueError(_UNAVAILABLE)
            return consumed


def prepare_native_reviewed_action(
    binding_id: UUID,
    action_id: UUID,
    approval_id: UUID,
    *,
    qualification: PreparedNativeControlBinding | None = None,
) -> PreparedNativeReviewedAction:
    """Reauthorize all original proofs without borrowing the worker's identity.

    These references are supplied by the fixed owner after SDK review linkage.
    The returned native admission establishes no portable acceptance itself.
    Remote policy checks precede the caller's SQL transaction and local fence.
    """
    with _authority_errors():
        action = prepare_native_control_command(binding_id, action_id, qualification=qualification)
        proposal = prepare_native_control_command(binding_id, action.command.proposal_id, qualification=qualification)
        approval = prepare_native_control_command(binding_id, approval_id, qualification=qualification)
        if (
            action.command.kind != "action"
            or action.command.id != action.command.action_id
            or proposal.command.kind != "proposal"
            or approval.command.kind != "approval"
            or any(
                (item.command.action_id, item.command.proposal_id, item.command.verb, item.binding.view)
                != (action.command.action_id, action.command.proposal_id, action.command.verb, action.binding.view)
                for item in (proposal, approval)
            )
        ):
            raise ValueError(_UNAVAILABLE)
        return PreparedNativeReviewedAction(action, proposal, approval)
