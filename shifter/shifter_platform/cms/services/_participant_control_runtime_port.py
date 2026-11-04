"""Fixed owner callbacks into current native authorization and held Engine work."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from django.db import connections, transaction
from pydantic import SecretStr

from engine.services import (
    begin_prepared_native_power_invocation,
    commit_native_participant_power,
    prepare_native_participant_operation,
    prepare_native_participant_power,
    prepare_native_power_invocation,
    record_native_participant_admission,
    release_native_participant_power,
)
from shared.credentials import CredentialContext
from shared.native_participant import (
    NativeControlCommandRecord,
    NativeParticipantPowerAction,
    NativePowerInvocationGrant,
)

from ._participant_control_authority import prepare_native_control_command, prepare_native_reviewed_action
from ._participant_control_binding import PreparedNativeControlBinding, prepare_native_control_binding
from ._participant_control_commands import native_control_command_catalog

_UNAVAILABLE = "Native participant authority unavailable"


@contextmanager
def _callback() -> Iterator[None]:
    """SDK callbacks run on dedicated backend threads, each with native DB custody."""
    try:
        yield
    except Exception:  # noqa: BLE001  # no native or source diagnostics cross into SDK records
        raise ValueError(_UNAVAILABLE) from None
    finally:
        connections.close_all()


@dataclass(frozen=True, slots=True)
class NativeParticipantRuntimePort:
    """One immutable native routing context; callers cannot select providers or actors."""

    binding_id: UUID
    bootstrap_credential: CredentialContext = field(repr=False)
    qualification: PreparedNativeControlBinding = field(repr=False)

    def commands(self) -> tuple[NativeControlCommandRecord, ...]:
        """Read original requests for historical validation, granting no current permission."""
        with _callback():
            return native_control_command_catalog(self.binding_id)

    def authorize(self, command_id: UUID | None, *, approval_id: UUID | None = None) -> None:
        """Resolve current authority outside SQL, then retain all local admission fences."""
        with _callback():
            if command_id is None:
                admission = prepare_native_control_binding(
                    self.bootstrap_credential, self.binding_id, qualification=self.qualification
                )
                with transaction.atomic():
                    admission.fence()
                return
            if approval_id is not None:
                reviewed = prepare_native_reviewed_action(
                    self.binding_id, command_id, approval_id, qualification=self.qualification
                )
                with transaction.atomic():
                    reviewed.fence()
            else:
                command = prepare_native_control_command(self.binding_id, command_id, qualification=self.qualification)
                if command.command.kind == "action":
                    raise ValueError(_UNAVAILABLE)
                with transaction.atomic():
                    command.fence()

    def reserve(self, action: NativeParticipantPowerAction) -> UUID:
        """Recheck original requester, human reviewer and consumer before strict held admission."""
        with _callback():
            reviewed = prepare_native_reviewed_action(
                self.binding_id, UUID(action.action_id), UUID(action.approval_ref), qualification=self.qualification
            )
            binding = reviewed.action.binding
            if (
                action.coordinates != binding.view.coordinates
                or action.episode_id != f"episode:{action.coordinates.run_id}"
            ):
                raise ValueError(_UNAVAILABLE)
            native = prepare_native_participant_power(
                reviewed.action.command.credential,
                binding.request_id,
                action,
                authority_target=binding.authority_target,
            )
            with transaction.atomic():
                reviewed.fence()
                return commit_native_participant_power(native)

    def release(self, action: NativeParticipantPowerAction, portable_operation_id: UUID) -> UUID:
        """Fixed-owner-only release after its successful SDK receipt and current-cut read."""
        with _callback():
            reviewed = prepare_native_reviewed_action(
                self.binding_id, UUID(action.action_id), UUID(action.approval_ref), qualification=self.qualification
            )
            binding = reviewed.action.binding
            if action.coordinates != binding.view.coordinates:
                raise ValueError(_UNAVAILABLE)
            credential = reviewed.action.command.credential
            native = prepare_native_participant_operation(
                credential,
                UUID(action.action_id),
                action.control_cut_digest,
                authority_target=binding.authority_target,
            )
            with transaction.atomic():
                reviewed.fence()
                record_native_participant_admission(
                    credential,
                    UUID(action.action_id),
                    portable_operation_uuid=portable_operation_id,
                    control_cut_digest=action.control_cut_digest,
                    authority_target=binding.authority_target,
                    admission=native,
                )
                return release_native_participant_power(
                    credential,
                    UUID(action.action_id),
                    portable_operation_uuid=portable_operation_id,
                    control_cut_digest=action.control_cut_digest,
                    authority_target=binding.authority_target,
                    admission=native,
                )

    def begin_invocation(
        self, action: NativeParticipantPowerAction, *, member_ref: str, token: SecretStr, attempt_id: UUID
    ) -> NativePowerInvocationGrant:
        """Recheck all original proofs immediately before consuming a verified Job's grant."""
        with _callback():
            reviewed = prepare_native_reviewed_action(
                self.binding_id, UUID(action.action_id), UUID(action.approval_ref), qualification=self.qualification
            )
            if action.coordinates != reviewed.action.binding.view.coordinates:
                raise ValueError(_UNAVAILABLE)
            native = prepare_native_power_invocation(
                action_id=UUID(action.action_id),
                member_ref=member_ref,
                control_cut_digest=action.control_cut_digest,
                token=token,
                attempt_id=attempt_id,
            )
            with transaction.atomic():
                reviewed.fence()
                return begin_prepared_native_power_invocation(native)
