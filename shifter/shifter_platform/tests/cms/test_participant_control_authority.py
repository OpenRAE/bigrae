"""Original request, human review and consuming proof are independent live gates."""

from uuid import uuid4

import pytest

from shared.native_participant import NativeControlSubmission
from tests.cms.test_participant_control_requests import (
    controlled_pack,
    controlled_source,
    native_request,
    product_range,
    tenant,
)

__all__ = ["controlled_pack", "controlled_source", "native_request", "product_range", "tenant"]
pytestmark = pytest.mark.django_db


def service(case, name):
    from management.services import create_service_principal
    from shared.authorization import CredentialCeiling
    from shared.credentials import CredentialContext
    from tests._credential_helpers import persisted_credential

    principal = create_service_principal(name)
    case.item.case.actor.policy_principals.add(principal.uuid)
    return persisted_credential(
        CredentialContext(
            principal,
            "service",
            uuid4(),
            CredentialCeiling(frozenset({"event.manage_ranges"})),
            frozenset({"authorization:event.manage_ranges"}),
        )
    )


@pytest.fixture
def reviewed(native_request):
    from cms.services import prepare_native_control_binding
    from cms.services._participant_control_commands import persist_native_control_command
    from shared.raes.native_supervisory_requests import (
        build_native_power_action_submission,
        build_native_power_control_request,
    )

    case = native_request
    requester = service(case, "Synthetic original requester")
    consumer = service(case, "Synthetic reviewed action consumer")
    request_admission = prepare_native_control_binding(requester, case.admission.view.id)
    persist_native_control_command(
        request_admission,
        request_id=case.request_id,
        kind="proposal",
        verb="pause",
        proposal_id=case.request_id,
        action_id=case.action_id,
        request=case.prepared,
    )
    approval_id = uuid4()
    decision = build_native_power_control_request(
        model=case.candidate.model,
        snapshot=case.owner.snapshot,
        binding=case.candidate.bindings[0],
        episode_id=case.episode,
        source_ref=str(case.admission.configuration.id),
        evidence_ref=f"urn:shifter:control-command:{approval_id}",
        submission=NativeControlSubmission(
            kind="approval",
            request_id=approval_id,
            proposal_id=case.request_id,
            action_id=case.action_id,
            expected_cut_digest=case.prepared.control_cut_digest,
            verb=case.candidate.bindings[0].verb,
        ),
    )
    persist_native_control_command(
        case.admission,
        request_id=approval_id,
        kind="approval",
        verb="pause",
        proposal_id=case.request_id,
        action_id=case.action_id,
        request=decision,
    )
    action = build_native_power_action_submission(
        owner=case.owner,
        model=case.candidate.model,
        binding=case.candidate.bindings[0],
        episode_id=case.episode,
        proposal_id=case.request_id,
        action_id=case.action_id,
        expected_cut_digest=case.prepared.control_cut_digest,
    )
    persist_native_control_command(
        prepare_native_control_binding(consumer, case.admission.view.id),
        request_id=case.action_id,
        kind="action",
        verb="pause",
        proposal_id=case.request_id,
        action_id=case.action_id,
        request=action,
    )
    return case, requester, consumer, approval_id


def test_reviewed_action_requires_all_three_original_native_proofs(reviewed):
    from django.db import transaction

    from cms.services._participant_control_authority import prepare_native_reviewed_action

    case, requester, consumer, approval_id = reviewed
    prepared = prepare_native_reviewed_action(case.admission.view.id, case.action_id, approval_id)
    assert prepared.action.command.credential == consumer
    assert prepared.proposal.command.credential == requester
    assert prepared.approval.command.credential == case.item.case.credential
    with transaction.atomic():
        assert prepared.fence() == case.admission.native.input


@pytest.mark.parametrize("revoked", ["requester", "reviewer", "consumer"])
def test_revocation_of_any_original_proof_prevents_reviewed_effect_admission(reviewed, revoked):
    from cms.services._participant_control_authority import prepare_native_reviewed_action

    case, requester, consumer, approval_id = reviewed
    principal = {
        "requester": requester.principal,
        "reviewer": case.item.case.credential.principal,
        "consumer": consumer.principal,
    }[revoked]
    case.item.case.actor.policy_principals.remove(principal.uuid)
    with pytest.raises(ValueError, match="Native participant authority unavailable"):
        prepare_native_reviewed_action(case.admission.view.id, case.action_id, approval_id)


def test_unrelated_decision_cannot_be_used_as_the_native_approval(reviewed):
    from cms.services._participant_control_authority import prepare_native_reviewed_action

    case, _, _, _ = reviewed
    with pytest.raises(ValueError, match="Native participant authority unavailable"):
        prepare_native_reviewed_action(case.admission.view.id, case.action_id, uuid4())


@pytest.mark.parametrize("revoked", ["requester", "reviewer", "consumer"])
def test_review_revocation_after_preparation_fails_the_local_commit_fence(reviewed, revoked):
    from django.db import transaction

    from cms.services._participant_control_authority import prepare_native_reviewed_action
    from management.models import PrincipalSession, ServiceCredentialAdmission

    case, requester, consumer, approval_id = reviewed
    prepared = prepare_native_reviewed_action(case.admission.view.id, case.action_id, approval_id)
    credential = {"requester": requester, "reviewer": case.item.case.credential, "consumer": consumer}[revoked]
    if revoked == "reviewer":
        PrincipalSession.objects.filter(credential_uuid=credential.credential_uuid).delete()
    else:
        ServiceCredentialAdmission.objects.filter(uuid=credential.credential_uuid).update(is_active=False)
    with transaction.atomic(), pytest.raises(ValueError, match="Native participant authority unavailable"):
        prepared.fence()


@pytest.mark.parametrize("cancelled", [False, True])
def test_settlement_fences_a_prepared_callback_even_before_any_native_reservation(reviewed, cancelled):
    from django.db import transaction

    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_authority import prepare_native_reviewed_action
    from cms.services._participant_control_commands import load_native_control_command
    from cms.services._participant_control_settlement import settle_native_control_dispatch

    case, _, _, approval_id = reviewed
    prepared = prepare_native_reviewed_action(case.admission.view.id, case.action_id, approval_id)
    with transaction.atomic():
        assert prepared.fence() == case.admission.native.input
    command = load_native_control_command(case.admission.view.id, case.action_id)
    settle_native_control_dispatch(command, case.admission.view.coordinates, cancelled_review=cancelled)
    assert ParticipantControlCommand.objects.get(pk=case.action_id).dispatch_fenced_at is not None
    with transaction.atomic(), pytest.raises(ValueError, match="Native participant authority unavailable"):
        prepared.fence()


def test_settlement_strict_audit_failure_cannot_partially_fence_a_command(reviewed, monkeypatch):
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_commands import load_native_control_command
    from cms.services._participant_control_settlement import settle_native_control_dispatch

    case, _, _, _ = reviewed
    command = load_native_control_command(case.admission.view.id, case.action_id)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic command settlement audit unavailable")

    monkeypatch.setattr("cms.services._participant_control_settlement.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="settlement audit unavailable"):
        settle_native_control_dispatch(command, case.admission.view.coordinates)
    assert ParticipantControlCommand.objects.get(pk=case.action_id).dispatch_fenced_at is None
