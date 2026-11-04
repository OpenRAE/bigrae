"""The CTF subject seam retains current event policy and exact assignment."""

from uuid import uuid4

import pytest
from django.db import transaction

from shared.participant_control_authority import admit_participant_subject

pytestmark = pytest.mark.django_db


@pytest.fixture
def assignment(ctf_event_active, participant_user):
    from ctf.models import CTFParticipant

    return CTFParticipant.objects.create(
        event=ctf_event_active,
        user=participant_user,
        name="Synthetic controlled participant",
        status="active",
        range_instance_id=4242,
        range_request_id=uuid4(),
    )


def test_ctf_owner_resolves_exact_subject_before_fencing(assignment, organizer_credential):
    admission = admit_participant_subject(organizer_credential, "ctf", assignment.pk)
    assert admission.subject.subject_uuid == assignment.pk
    assert admission.subject.event_uuid == assignment.event_id
    assert admission.subject.range_instance_pk == 4242
    assert admission.credential == organizer_credential
    with transaction.atomic():
        admission.fence()


@pytest.mark.parametrize(
    "fault", ["range", "request", "status", "role", "event-status", "event-deadline", "event-custody", "proof"]
)
def test_assignment_fence_refuses_changed_facts(assignment, organizer_credential, fault):
    from ctf.models import CTFEvent, CTFParticipant

    admission = admit_participant_subject(organizer_credential, "ctf", assignment.pk)
    if fault == "range":
        CTFParticipant.objects.filter(pk=assignment.pk).update(range_instance_id=5555)
    elif fault == "request":
        CTFParticipant.objects.filter(pk=assignment.pk).update(range_request_id=uuid4())
    elif fault == "status":
        CTFParticipant.objects.filter(pk=assignment.pk).update(status="banned")
    elif fault == "role":
        CTFParticipant.objects.filter(pk=assignment.pk).update(role="observer")
    elif fault == "event-status":
        CTFEvent.objects.filter(pk=assignment.event_id).update(status="ended")
    elif fault == "event-custody":
        CTFEvent.objects.filter(pk=assignment.event_id).update(owner_principal_uuid=uuid4())
    elif fault == "event-deadline":
        from datetime import timedelta

        from django.utils import timezone

        CTFEvent.objects.filter(pk=assignment.event_id).update(event_end=timezone.now() - timedelta(seconds=1))
    else:
        from management.models import Principal

        Principal.objects.filter(uuid=organizer_credential.principal.uuid).update(is_active=False)
    with pytest.raises(ValueError), transaction.atomic():
        admission.fence()


def test_assignment_is_not_permission_for_the_participant(assignment, participant_user, live_session_credential):
    participant_credential = live_session_credential(participant_user)
    with pytest.raises(ValueError, match="Participant subject unavailable"):
        admit_participant_subject(participant_credential, "ctf", assignment.pk)


@pytest.mark.parametrize("product", ["ctf", "unknown"])
def test_unknown_subject_or_product_is_a_bounded_denial(organizer_credential, product):
    with pytest.raises(ValueError, match="Participant subject unavailable"):
        admit_participant_subject(organizer_credential, product, uuid4())
