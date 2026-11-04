"""CTF owns current participant/event assignment for the native control worker."""

from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.models import CTFEvent, CTFParticipant
from ctf.services.actors import EventActionAdmission
from ctf.services.authorization import admit_event_actions, assert_event_action
from shared.credentials import CredentialContext
from shared.participant_control_authority import (
    NativeParticipantSubject,
    NativeParticipantSubjectAdmission,
)

_UNAVAILABLE = "Participant control assignment unavailable"
_PARTICIPANT_FIELDS = (
    "event_id",
    "range_instance_id",
    "range_request_id",
    "principal_uuid",
    "status",
    "role",
    "deleted_at",
)


def _participant_binding(participant: CTFParticipant) -> tuple[object, ...]:
    return tuple(getattr(participant, name) for name in _PARTICIPANT_FIELDS)


def _require_operating_assignment(event: CTFEvent, participant: CTFParticipant) -> None:
    now = timezone.now()
    if (
        event.status not in {"active", "paused"}
        or event.deleted_at is not None
        or not event.event_start <= now < event.event_end
        or participant.deleted_at is not None
        or participant.status not in {"registered", "active"}
        or participant.role != "player"
        or participant.principal_uuid is None
        or participant.range_instance_id is None
        or participant.range_request_id is None
    ):
        raise ValueError(_UNAVAILABLE)


def _fence_assignment(admission: EventActionAdmission, subject_uuid: UUID, binding: tuple[object, ...]) -> None:
    if not transaction.get_connection().in_atomic_block:
        raise ValueError("Participant assignment fence requires a transaction")
    event = CTFEvent.objects.select_for_update().get(pk=admission.event_uuid)
    participant = CTFParticipant.objects.select_for_update().get(pk=subject_uuid, event=event)
    _require_operating_assignment(event, participant)
    assert_event_action(admission, event, "event.manage_ranges")
    if _participant_binding(participant) != binding:
        raise ValueError(_UNAVAILABLE)


def admit_ctf_participant_control(
    credential: CredentialContext, subject_uuid: UUID
) -> NativeParticipantSubjectAdmission:
    """Evaluate live event policy before locks; never infer it from range ownership."""
    participant = CTFParticipant.objects.select_related("event").get(pk=subject_uuid)
    _require_operating_assignment(participant.event, participant)
    admission = admit_event_actions(credential, participant.event, "event.manage_ranges")
    assert participant.range_instance_id is not None
    subject = NativeParticipantSubject("ctf", participant.pk, participant.event_id, participant.range_instance_id)
    return NativeParticipantSubjectAdmission(
        subject,
        admission.credential,
        partial(_fence_assignment, admission, subject_uuid, _participant_binding(participant)),
    )
