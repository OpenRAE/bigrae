"""One persistent released owner for the fixed native supervision integration."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from raes_contracts.runtime_state import OperationKind
from raes_runtime.control_plane_operation_context import operation_actor_scope
from raes_runtime.control_plane_security import ControlPlaneIdentity, ControlPlaneRole, ParticipantControlSubjectBinding

from shared.native_participant import (
    NativeControlCommandKind,
    NativeControlCommandRecord,
    NativeControlOperationView,
    NativeControlSubmission,
    NativeParticipantPowerAction,
    NativePowerControlSelection,
    NativePreparedControlRequest,
    NativeRuntimeCoordinates,
    NativeSupervisionCursor,
)
from shared.raes.native_participant_actions import _native_action, _require_proposal, native_participant_control_cut
from shared.raes.native_power_authority import native_power_crossing_evidence
from shared.raes.native_power_candidate import NativePowerControlCandidate
from shared.raes.native_request_binding import validate_prepared_native_power_request
from shared.raes.native_supervision_cursor import native_supervision_cursor
from shared.raes.native_supervisory_requests import (
    build_native_power_action_submission,
    build_native_power_control_request,
    parse_native_power_action_request,
    parse_native_power_control_request,
)

if TYPE_CHECKING:
    from raes_runtime.control_plane import RuntimeControlPlane
    from raes_runtime.control_plane_store import ControlPlaneStore
    from raes_runtime.participant_crossing_mediation import (
        ParticipantCrossingEvidence,
    )


_UNAVAILABLE = "Native participant request unavailable"


@dataclass(slots=True)
class NativePowerSession:
    """Native serialization beside SDK-owned history, policy and operation state.

    Only the installed owner retains this object. Authorization, command
    persistence and strict audit belong to the injecting native service.
    """

    binding_id: UUID
    coordinates: NativeRuntimeCoordinates
    _selection: NativePowerControlSelection = field(repr=False)
    _source_ref: str = field(repr=False)
    _candidate: NativePowerControlCandidate = field(repr=False)
    _owner: RuntimeControlPlane = field(repr=False)
    _store: ControlPlaneStore = field(repr=False)
    _has_unresolved_invocation: Callable[[], bool] = field(repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def episode_id(self) -> str:
        """Keep the episode fixed for this run, including after process recovery."""
        return f"episode:{self.coordinates.run_id}"

    @property
    def cursor(self) -> NativeSupervisionCursor:
        """Project the released current fold, never a native controller-state copy."""
        with self._lock:
            return native_supervision_cursor(
                model=self._candidate.model,
                snapshot=self._owner.snapshot,
                participant_address=self._selection.participant_address,
                episode_id=self.episode_id,
            )

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Serialize native invocation admission with all portable mutations."""
        with self._lock:
            if self._has_unresolved_invocation():
                raise ValueError("Native invocation remains unresolved")
            yield

    def _identity(self, principal_uuid: UUID) -> ControlPlaneIdentity:
        return ControlPlaneIdentity(
            identity=f"urn:shifter:principal:{principal_uuid}",
            target_name=self._owner.target_name,
            roles=frozenset({ControlPlaneRole.OPERATOR}),
            participant_control_subjects=(
                ParticipantControlSubjectBinding(
                    self._selection.participant_address,
                    self._selection.controller_address,
                ),
            ),
        )

    def prepare(
        self,
        *,
        kind: NativeControlCommandKind,
        verb: Literal["pause", "resume"],
        request_id: UUID,
        proposal_id: UUID,
        action_id: UUID,
        expected_cut_digest: str,
        decision_id: UUID | None = None,
    ) -> NativePreparedControlRequest:
        """Prepare original bytes at the caller's exact observed cut, without admission."""
        with self._lock:
            binding = next((item for item in self._candidate.bindings if item.verb == verb), None)
            if binding is None:
                raise ValueError(_UNAVAILABLE)
            if kind == "action":
                if decision_id is not None:
                    raise ValueError(_UNAVAILABLE)
                return build_native_power_action_submission(
                    owner=self._owner,
                    model=self._candidate.model,
                    binding=binding,
                    episode_id=self.episode_id,
                    proposal_id=proposal_id,
                    action_id=action_id,
                    expected_cut_digest=expected_cut_digest,
                )
            return build_native_power_control_request(
                model=self._candidate.model,
                snapshot=self._owner.snapshot,
                binding=binding,
                episode_id=self.episode_id,
                source_ref=self._source_ref,
                evidence_ref=f"urn:shifter:control-command:{request_id}",
                submission=NativeControlSubmission(
                    kind=kind,
                    request_id=request_id,
                    proposal_id=proposal_id,
                    action_id=action_id,
                    expected_cut_digest=expected_cut_digest,
                    decision_id=decision_id,
                    verb=binding.verb,
                ),
            )

    def submit(
        self,
        command: NativeControlCommandRecord,
        *,
        crossing_evidence: ParticipantCrossingEvidence | None = None,
        allowed_decision_ids: frozenset[UUID] = frozenset(),
    ) -> NativeControlOperationView:
        """Submit the durable original request; exact retries stay SDK-owned."""
        with self.mutation():
            if command.binding_id != self.binding_id:
                raise ValueError(_UNAVAILABLE)
            validate_prepared_native_power_request(
                command.request,
                coordinates=self.coordinates,
                selection=self._selection,
                allowed_decision_ids=allowed_decision_ids,
                submission=NativeControlSubmission(
                    request_id=command.id,
                    kind=command.kind,
                    verb=command.verb,
                    proposal_id=command.proposal_id,
                    action_id=command.action_id,
                    expected_cut_digest=getattr(command.request, "control_cut_digest", ""),
                ),
            )
            identity = self._identity(command.credential.principal.uuid)
            original = self._store.find_by_idempotency(f"native-command:{command.id}")
            if original is not None:
                context = original.receipt.context
                actor, scopes = operation_actor_scope(identity)
                allowed_kinds = {OperationKind.PARTICIPANT_CROSSING}
                if command.kind != "action":
                    allowed_kinds.add(OperationKind.PARTICIPANT_CONTROL)
                if (
                    context.actor_id != actor
                    or context.authorization_scope != scopes
                    or context.target_scope != f"target:{self._owner.target_name}"
                    or context.run_scope != f"run:{self.coordinates.run_id}"
                    or context.operation_kind not in allowed_kinds
                ):
                    raise ValueError(_UNAVAILABLE)
                observed = self._owner.get_operation(original.receipt.operation_id, identity=identity)
                if observed is None:
                    raise ValueError(_UNAVAILABLE)
                return NativeControlOperationView(command.id, UUID(observed.operation_id), observed.state.value)
            if crossing_evidence is None:
                crossing_evidence = native_power_crossing_evidence(self.binding_id, self._source_ref, command.id)
            options = {
                "identity": identity,
                "idempotency_key": f"native-command:{command.id}",
                "crossing_evidence": crossing_evidence,
            }
            if command.kind == "action":
                receipt = self._owner.admit_participant_action(
                    self._candidate.model.participant_behaviors[self._selection.participant_address],
                    parse_native_power_action_request(command.request.intent_json),
                    **options,
                )
            else:
                receipt = self._owner.record_participant_control(
                    self._selection.participant_address,
                    parse_native_power_control_request(command.request.intent_json),
                    **options,
                )
            status = self._owner.get_operation(receipt.operation_id, identity=identity)
            if status is None:
                raise ValueError(_UNAVAILABLE)
            return NativeControlOperationView(command.id, UUID(receipt.operation_id), status.state.value)

    def close(self) -> None:
        """Retain ownership until both native invocation and SDK callbacks have drained."""
        with self.mutation():
            self._owner.close()

    def operation_state(self, operation_id: UUID) -> str | None:
        """Read only an SDK-owned status for an independently authorized native reference."""
        with self._lock:
            status = self._owner.get_operation(str(operation_id))
            return None if status is None else status.state.value

    def action_at_current_cut(
        self, command: NativeControlCommandRecord, portable_operation_id: UUID
    ) -> NativeParticipantPowerAction:
        """Verify an owning receipt and expose its exact native meaning at the live cut."""
        with self._lock:
            if (
                command.binding_id != self.binding_id
                or command.kind != "action"
                or command.portable_operation_id != portable_operation_id
            ):
                raise ValueError(_UNAVAILABLE)
            status = self._owner.get_operation(
                str(portable_operation_id), identity=self._identity(command.credential.principal.uuid)
            )
            if (
                status is None
                or status.state.value != "succeeded"
                or status.context.operation_kind != OperationKind.PARTICIPANT_CROSSING
                or status.context.run_scope != f"run:{self.coordinates.run_id}"
            ):
                raise ValueError(_UNAVAILABLE)
            binding = next(item for item in self._candidate.bindings if item.verb == command.verb)
            request = parse_native_power_action_request(command.request.intent_json)
            approval = _require_proposal(binding, request, self._owner.snapshot, self.episode_id)
            return _native_action(
                binding,
                request,
                self.episode_id,
                approval_ref=approval,
                control_cut_digest=native_participant_control_cut(
                    self._owner.snapshot, binding.participant_address, self.episode_id
                ),
            )
