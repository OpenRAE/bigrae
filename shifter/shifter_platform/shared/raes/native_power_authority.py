"""Fixed native authorization adapter for released supervision and ingress gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from raes_contracts.canonical import canonical_json_digest
from raes_contracts.contracts.participant_action_admission import ParticipantActionAdmissionRequest
from raes_contracts.contracts.participant_control_occurrence_v2_policy import ParticipantControlOccurrencePolicyModel
from raes_contracts.contracts.participant_crossing import (
    ParticipantCrossingDirection,
    ParticipantCrossingOperation,
    ParticipantCrossingPolicyReferenceModel,
    ParticipantCrossingSubjectReferenceModel,
)
from raes_contracts.contracts.participant_crossing import (
    ParticipantCrossingGateDisposition as Gate,
)
from raes_contracts.errors import AuthorizationError
from raes_contracts.runtime_state import RuntimeSnapshot
from raes_processor.compiler import project_control_episode_policy
from raes_runtime.participant_control_intents import ParticipantControlIntent
from raes_runtime.participant_control_runtime import ParticipantControlLiveCut
from raes_runtime.participant_crossing_mediation import (
    ParticipantCrossingEvidence,
    ParticipantCrossingIntent,
    ParticipantCrossingPolicyResolution,
    ParticipantCrossingSemanticGates,
    ParticipantCrossingValidationContext,
)

from shared.native_participant import NativeControlAuthorityPort, NativeControlCommandRecord
from shared.raes.native_participant_actions import MAX_NATIVE_CONTROL_RECORDS, _require_proposal
from shared.raes.native_power_candidate import NativePowerControlCandidate
from shared.raes.native_supervision_cursor import native_supervision_cursor
from shared.raes.native_supervisory_requests import (
    parse_native_power_action_request,
    parse_native_power_control_request,
)

_DECLARATION = "shifter-native-power-supervision-candidate/v1"
_UNAVAILABLE = "Native participant authority unavailable"


def native_power_crossing_evidence(binding_id: UUID, source_ref: str, command_id: UUID) -> ParticipantCrossingEvidence:
    """Mint only the fixed native reference audience; no caller-controlled policy gates."""
    reference = f"urn:shifter:control-command:{command_id}"
    return ParticipantCrossingEvidence(
        audience_scope_ref=f"urn:shifter:control-audience:{binding_id}",
        required_evidence_refs=[reference, _DECLARATION],
        provenance_refs=[source_ref],
        evidence_refs=[reference, _DECLARATION],
        object_marking_refs=["shifter:native-control-references/v1"],
        authorization_scope=f"urn:shifter:control-binding:{binding_id}",
        loss_and_limitations=["shifter:dedicated-gce-native-power/v1"],
    )


@dataclass(frozen=True, slots=True)
class NativePowerAuthority:
    """Resolve immutable command identity on backend threads, never a current-actor slot."""

    binding_id: UUID
    source_ref: str
    candidate: NativePowerControlCandidate = field(repr=False)
    port: NativeControlAuthorityPort = field(repr=False)

    def _commands(self) -> tuple[NativeControlCommandRecord, ...]:
        records = self.port.commands()
        if (
            len(records) > MAX_NATIVE_CONTROL_RECORDS
            or len({item.id for item in records}) != len(records)
            or any(item.binding_id != self.binding_id for item in records)
        ):
            raise AuthorizationError(_UNAVAILABLE)
        return records

    def _command(self, command_id: UUID) -> NativeControlCommandRecord:
        found = [record for record in self._commands() if record.id == command_id]
        if len(found) != 1:
            raise AuthorizationError(_UNAVAILABLE)
        return found[0]

    def _authorize(self, command_id: UUID | None, *, approval_id: UUID | None = None) -> None:
        try:
            self.port.authorize(command_id, approval_id=approval_id)
        except Exception:  # noqa: BLE001  # native faults never become portable diagnostics
            raise AuthorizationError(_UNAVAILABLE) from None

    def _policy(self, episode_id: str) -> ParticipantControlOccurrencePolicyModel:
        first = self.candidate.bindings[0]
        if episode_id != f"episode:{first.coordinates.run_id}":
            raise AuthorizationError(_UNAVAILABLE)
        specifications = [
            item
            for item in self.candidate.model.behavior_specifications.values()
            if item.mixed_control_participant_address == first.participant_address
        ]
        if len(specifications) != 1:
            raise AuthorizationError(_UNAVAILABLE)
        return project_control_episode_policy(self.candidate.model, specifications[0].address, episode_id=episode_id)

    def _cut(
        self,
        policy: ParticipantControlOccurrencePolicyModel,
        snapshot: RuntimeSnapshot,
        *,
        request_ref: str,
        evidence_refs: list[str],
        initial: bool = False,
    ) -> ParticipantControlLiveCut:
        if policy != self._policy(policy.episode_id):
            raise AuthorizationError(_UNAVAILABLE)
        first = self.candidate.bindings[0]
        state_ref, order = policy.initial_state_ref, 0
        if not initial:
            cursor = native_supervision_cursor(
                model=self.candidate.model,
                snapshot=snapshot,
                participant_address=first.participant_address,
                episode_id=policy.episode_id,
            )
            state_ref, order = cursor.state_ref, cursor.next_order
        state = policy.state(state_ref)
        controller = self.candidate.model.participant_behaviors[first.controller_address]
        if (
            state is None
            or state.controller_ref != first.controller_address
            or not set(state.authority_basis_refs)
            <= set(controller.authority_anchor_addresses or controller.authority_anchor_refs)
            or not set(state.scope_refs) <= set(first.target_addresses)
        ):
            raise AuthorizationError(_UNAVAILABLE)
        return ParticipantControlLiveCut(
            request_ref=request_ref,
            effective_order=order,
            active_authority_basis_refs=list(state.authority_basis_refs),
            authorized_scope_refs=list(first.target_addresses),
            evidence_refs=evidence_refs,
        )

    def resolve_cut(
        self,
        policy: ParticipantControlOccurrencePolicyModel,
        intent: ParticipantControlIntent | None,
        snapshot: RuntimeSnapshot,
    ) -> ParticipantControlLiveCut:
        """Resolve compiled authority only after current native proof admission."""
        if intent is None:
            self._authorize(None)
            return self._cut(
                policy,
                snapshot,
                request_ref=f"urn:shifter:control-binding:{self.binding_id}",
                evidence_refs=[self.source_ref],
                initial=True,
            )
        command = self._command(UUID(intent.client_correlation_id))
        if command.kind == "action" or parse_native_power_control_request(command.request.intent_json) != intent:
            raise AuthorizationError(_UNAVAILABLE)
        self._authorize(command.id)
        return self._cut(policy, snapshot, request_ref=str(command.id), evidence_refs=list(intent.evidence_refs))

    def _approval(self, command: NativeControlCommandRecord, snapshot: RuntimeSnapshot) -> UUID:
        request = parse_native_power_action_request(command.request.intent_json)
        binding = next(item for item in self.candidate.bindings if item.verb == command.verb)
        return UUID(_require_proposal(binding, request, snapshot, f"episode:{binding.coordinates.run_id}"))

    def resolve_action_cut(
        self,
        policy: ParticipantControlOccurrencePolicyModel,
        request: ParticipantActionAdmissionRequest,
        snapshot: RuntimeSnapshot,
    ) -> ParticipantControlLiveCut:
        """Fence the original approved action against the owning current cut."""
        command = self._command(UUID(request.action_instance_id))
        if command.kind != "action" or parse_native_power_action_request(command.request.intent_json) != request:
            raise AuthorizationError(_UNAVAILABLE)
        self._authorize(command.id, approval_id=self._approval(command, snapshot))
        return self._cut(
            policy, snapshot, request_ref=str(command.id), evidence_refs=[f"urn:shifter:control-command:{command.id}"]
        )

    def _crossing_policy(self, command: NativeControlCommandRecord) -> ParticipantCrossingPolicyReferenceModel:
        facts = {
            "profile": _DECLARATION,
            "binding_id": str(self.binding_id),
            "command_id": str(command.id),
            "requested_cut": command.request.control_cut_digest,
        }
        return ParticipantCrossingPolicyReferenceModel(
            policy_id=f"urn:shifter:control-ingress:{self.binding_id}:{command.id}",
            policy_revision="1",
            policy_digest=canonical_json_digest(facts),
            policy_decision_ref=f"urn:shifter:control-command:{command.id}",
            decision_cut_ref=command.request.control_cut_digest,
            effective_order=0,
            valid_from_order=0,
            valid_until_order=MAX_NATIVE_CONTROL_RECORDS * 8,
        )

    def resolve(
        self, intent: ParticipantCrossingIntent, snapshot: RuntimeSnapshot
    ) -> ParticipantCrossingPolicyResolution:
        """Resolve only the fixed crossing for one original native command."""
        commands = [
            item
            for item in self._commands()
            if ParticipantCrossingSubjectReferenceModel.model_validate_json(item.request.subject_json) == intent.subject
        ]
        if len(commands) != 1:
            raise AuthorizationError(_UNAVAILABLE)
        command = commands[0]
        expected = native_power_crossing_evidence(self.binding_id, self.source_ref, command.id)
        first = self.candidate.bindings[0]
        if (
            intent.direction != ParticipantCrossingDirection.INGRESS
            or intent.requested_operation != ParticipantCrossingOperation.ADMISSION
            or intent.controller_ref != first.controller_address
            or any(getattr(intent, key) != value for key, value in expected.model_dump().items())
        ):
            raise AuthorizationError(_UNAVAILABLE)
        permitted = True
        try:
            self._authorize(
                command.id, approval_id=self._approval(command, snapshot) if command.kind == "action" else None
            )
        except AuthorizationError:
            permitted = False
        return ParticipantCrossingPolicyResolution(
            policy=self._crossing_policy(command),
            gates=ParticipantCrossingSemanticGates(
                participant_authority=Gate.PERMIT if permitted else Gate.DENY,
                action_admission=Gate.PERMIT if permitted else Gate.DENY,
                visibility=Gate.NOT_APPLICABLE,
                marking_authorization=Gate.PERMIT,
                declassification=Gate.NOT_APPLICABLE,
                transformation_validity=Gate.NOT_APPLICABLE,
            ),
            reason_code="policy-satisfied" if permitted else "authority-denied",
        )

    def validation_context(
        self, snapshot: RuntimeSnapshot, participant_address: str
    ) -> ParticipantCrossingValidationContext:
        """Provide exact known subjects, policies, and evidence from native custody."""
        first = self.candidate.bindings[0]
        if participant_address != first.participant_address:
            raise AuthorizationError(_UNAVAILABLE)
        commands = self._commands()
        return ParticipantCrossingValidationContext(
            known_subjects=tuple(
                ParticipantCrossingSubjectReferenceModel.model_validate_json(item.request.subject_json)
                for item in commands
            ),
            policies=tuple(self._crossing_policy(item) for item in commands),
            known_evidence_refs=frozenset(
                {self.source_ref, _DECLARATION, *(f"urn:shifter:control-command:{item.id}" for item in commands)}
            ),
            known_authority_basis_refs=frozenset(
                reference
                for address in (first.participant_address, first.controller_address)
                for reference in (
                    self.candidate.model.participant_behaviors[address].authority_anchor_addresses
                    or self.candidate.model.participant_behaviors[address].authority_anchor_refs
                )
            ),
        )
