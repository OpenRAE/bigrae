"""One fixed CMS runtime owner; native routes retain it beyond individual requests."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from django.db import transaction
from pydantic import SecretStr

from cms.models import ParticipantControlBinding, ParticipantControlCommand
from engine.services import native_participant_power_requires_exclusion, native_participant_power_was_released
from shared.credentials import CredentialContext
from shared.native_participant import (
    NativeControlCommandRecord,
    NativeControlOperationView,
    NativeControlSubmission,
    NativePowerInvocationGrant,
    NativePowerInvocationRoute,
    NativeSupervisionCursor,
)
from shared.raes.native_power_session import NativePowerSession
from shared.raes.native_power_session_factory import NativePowerSessionConfiguration, open_native_power_session
from shared.raes.native_supervisory_requests import native_power_retry_request

from ._participant_control_binding import prepare_native_control_binding
from ._participant_control_commands import (
    correlate_native_control_operation,
    load_native_control_command,
    persist_native_control_command,
)
from ._participant_control_installation import require_native_control_policy
from ._participant_control_runtime_port import NativeParticipantRuntimePort
from ._participant_control_settlement import settle_native_control_dispatch

_UNAVAILABLE = "Native participant request unavailable"


@dataclass(frozen=True, slots=True)
class NativeParticipantControlOwner:
    """Keep the SDK's store and serializer with one immutable native ownership context."""

    session: NativePowerSession = field(repr=False)
    port: NativeParticipantRuntimePort = field(repr=False)

    def cursor(self, credential: CredentialContext) -> NativeSupervisionCursor:
        """Authorize the current native assignment before its bounded request-coordinate view."""
        admission = prepare_native_control_binding(
            credential, self.port.binding_id, qualification=self.port.qualification
        )
        with transaction.atomic():
            admission.fence()
        return self.session.cursor

    def submit(
        self,
        credential: CredentialContext,
        submission: NativeControlSubmission,
    ) -> NativeControlOperationView:
        """Audit original native intent, submit through released ingress and release only observed admission."""
        request_id, kind, verb = submission.request_id, submission.kind, submission.verb
        proposal_id, action_id = submission.proposal_id, submission.action_id
        expected_cut_digest, decision_id = submission.expected_cut_digest, submission.decision_id
        admission = prepare_native_control_binding(
            credential, self.port.binding_id, qualification=self.port.qualification
        )
        if admission.view.coordinates != self.session.coordinates:
            raise ValueError(_UNAVAILABLE)
        command = None
        if ParticipantControlCommand.objects.filter(pk=request_id).exists():
            original = load_native_control_command(self.port.binding_id, request_id)
            if original.request.control_cut_digest != expected_cut_digest:
                raise ValueError(_UNAVAILABLE)
            prepared = native_power_retry_request(original, decision_id=decision_id)
            command = persist_native_control_command(
                admission,
                request_id=request_id,
                kind=kind,
                verb=verb,
                proposal_id=proposal_id,
                action_id=action_id,
                request=prepared,
            )
            previous = self._retained_result(command)
            if previous is not None:
                return previous
        with self.session.mutation():
            if command is None:
                prepared = self.session.prepare(
                    kind=kind,
                    verb=verb,
                    request_id=request_id,
                    proposal_id=proposal_id,
                    action_id=action_id,
                    expected_cut_digest=expected_cut_digest,
                    decision_id=decision_id,
                )
                command = persist_native_control_command(
                    admission,
                    request_id=request_id,
                    kind=kind,
                    verb=verb,
                    proposal_id=proposal_id,
                    action_id=action_id,
                    request=prepared,
                )
            decisions = frozenset(
                ParticipantControlCommand.objects.filter(
                    binding_id=self.port.binding_id,
                    proposal_uuid=proposal_id,
                    kind__in=["approval", "denial"],
                ).values_list("pk", flat=True)
            )
            outcome = self.session.submit(command, allowed_decision_ids=decisions)
            command = correlate_native_control_operation(self.port.binding_id, command.id, outcome.operation_id)
            if outcome.state in {"failed", "cancelled"}:
                settle_native_control_dispatch(command, self.session.coordinates)
            elif command.kind == "cancellation" and outcome.state == "succeeded":
                settle_native_control_dispatch(command, self.session.coordinates, cancelled_review=True)
            if command.kind == "action" and outcome.state == "succeeded":
                self.port.release(
                    self.session.action_at_current_cut(command, outcome.operation_id), outcome.operation_id
                )
            return outcome

    def _retained_result(self, command: NativeControlCommandRecord) -> NativeControlOperationView | None:
        """Read an original receipt without re-entering a completed crossing."""
        if command.portable_operation_id is None:
            return None
        observed = self.session.operation_state(command.portable_operation_id)
        if observed in {"failed", "cancelled"}:
            settle_native_control_dispatch(command, self.session.coordinates)
        elif command.kind != "action" and observed == "succeeded":
            if command.kind == "cancellation":
                settle_native_control_dispatch(command, self.session.coordinates, cancelled_review=True)
        elif command.kind == "action" and native_participant_power_was_released(
            self.session.coordinates,
            command.action_id,
            command.portable_operation_id,
        ):
            if observed != "succeeded":
                raise ValueError(_UNAVAILABLE)
        else:
            return None
        assert observed is not None
        return NativeControlOperationView(command.id, command.portable_operation_id, observed)

    def close(self) -> None:
        """Refuse release of an unresolved native invocation or active SDK callback."""
        self.session.close()

    def begin_invocation(
        self, route: NativePowerInvocationRoute, *, member_ref: str, token: SecretStr, attempt_id: UUID
    ) -> NativePowerInvocationGrant:
        """Use Engine-authenticated routing, then fence one live cut through native grant commit."""
        with self.session.mutation():
            if route.coordinates != self.session.coordinates:
                raise ValueError(_UNAVAILABLE)
            command = load_native_control_command(self.port.binding_id, route.action_id)
            if command.portable_operation_id is None:
                raise ValueError(_UNAVAILABLE)
            action = self.session.action_at_current_cut(command, command.portable_operation_id)
            if action.approval_ref != str(route.approval_id):
                raise ValueError(_UNAVAILABLE)
            grant = self.port.begin_invocation(action, member_ref=member_ref, token=token, attempt_id=attempt_id)
            if grant.operation_id != route.operation_id:
                raise ValueError(_UNAVAILABLE)
            return grant


def open_native_participant_control_owner(
    credential: CredentialContext,
    binding_id: UUID,
    *,
    store_root: Path,
) -> NativeParticipantControlOwner:
    """Private worker-only construction; installation owns storage and process lifetime."""
    admission = prepare_native_control_binding(credential, binding_id)
    installed = require_native_control_policy(admission.configuration.runtime_policy_digest)
    with transaction.atomic():
        admission.fence()
    port = NativeParticipantRuntimePort(binding_id, credential, admission)
    coordinates = admission.view.coordinates
    initialized = ParticipantControlBinding.objects.get(pk=binding_id).runtime_initialized_at is not None
    with admission.source_path() as source:
        session = open_native_power_session(
            NativePowerSessionConfiguration(
                binding_id=binding_id,
                scenario_path=source,
                context=admission.native.input.compiler.context,
                coordinates=coordinates,
                power=admission.native.input.power,
                selection=admission.configuration.selection,
                port=port,
                authority_port=port,
                store_root=store_root,
                source_ref=f"urn:shifter:control-configuration:{admission.configuration.id}",
                principal_uuid=credential.principal.uuid,
                has_unresolved_invocation=lambda: native_participant_power_requires_exclusion(coordinates),
                budgets=installed.budgets,
                allow_initialize=not initialized,
            )
        )
    try:
        from django.utils import timezone

        from shared.audit import AuditEntityType, AuditEvent, audit_log, principal_actor_fields

        with transaction.atomic():
            admission.fence()
            row = ParticipantControlBinding.objects.select_for_update().get(pk=binding_id)
            if row.runtime_initialized_at is None:
                row.runtime_initialized_at = timezone.now()
                row.save(update_fields=["runtime_initialized_at"])
                audit_log(
                    AuditEvent(
                        entity_type=AuditEntityType.RANGE,
                        entity_id=0,
                        entity_ref=str(row.range_uuid),
                        action="update",
                        **principal_actor_fields(credential.principal),
                        request_id=str(admission.request_id),
                        new_state={
                            "participant_control_binding": str(binding_id),
                            "runtime_initialized": True,
                            "run_id": str(coordinates.run_id),
                        },
                    ),
                    strict=True,
                )
    except BaseException:
        session.close()
        raise
    return NativeParticipantControlOwner(session, port)
