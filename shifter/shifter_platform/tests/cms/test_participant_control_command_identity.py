"""Native requests and requesting proof cannot change after durable admission."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from tests.cms.test_participant_control_configuration import (
    configure,
    controlled_pack,
    controlled_source,
    make_binding,
    tenant,
)

__all__ = ["controlled_pack", "controlled_source", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.fixture
def command(controlled_pack):
    from cms.models import ParticipantControlCommand

    actor = controlled_pack[0]
    binding = make_binding(configure(controlled_pack).id)
    from shared.operation_authority import credential_reference_fields

    request_id = uuid4()
    return ParticipantControlCommand.objects.create(
        id=request_id,
        binding=binding,
        kind="proposal",
        verb="pause",
        proposal_uuid=request_id,
        action_uuid=uuid4(),
        request_json=b'{"synthetic":"request"}',
        subject_json=b'{"synthetic":"subject"}',
        control_cut_digest="sha256:" + "a" * 64,
        **credential_reference_fields(actor.credential),
    )


@pytest.mark.parametrize(
    "field", ["binding_id", "kind", "verb", "request_json", "credential_uuid", "control_cut_digest"]
)
def test_native_command_request_and_original_proof_are_immutable(command, field):
    from cms.models import ParticipantControlCommand

    values = {
        "binding_id": command.binding_id,
        "kind": "approval",
        "verb": "resume",
        "request_json": b'{"synthetic":"changed"}',
        "credential_uuid": uuid4(),
        "control_cut_digest": "sha256:" + "b" * 64,
    }
    if field == "binding_id":
        values[field] = make_binding(command.binding.configuration_id).pk
    with pytest.raises(IntegrityError), transaction.atomic():
        ParticipantControlCommand.objects.filter(pk=command.pk).update(**{field: values[field]})


def test_native_command_receipt_correlation_can_be_written_once(command):
    from cms.models import ParticipantControlCommand

    rows = ParticipantControlCommand.objects.filter(pk=command.pk)
    operation = uuid4()
    rows.update(portable_operation_uuid=operation)
    rows.update(portable_operation_uuid=operation)
    for replacement in (None, uuid4()):
        with pytest.raises(IntegrityError), transaction.atomic():
            rows.update(portable_operation_uuid=replacement)


def test_native_dispatch_fence_cannot_be_removed_or_replaced(command):
    from django.utils import timezone

    from cms.models import ParticipantControlCommand

    rows = ParticipantControlCommand.objects.filter(pk=command.pk)
    fence = timezone.now()
    rows.update(dispatch_fenced_at=fence)
    rows.update(dispatch_fenced_at=fence)
    for replacement in (None, timezone.now()):
        with pytest.raises(IntegrityError), transaction.atomic():
            rows.update(dispatch_fenced_at=replacement)
