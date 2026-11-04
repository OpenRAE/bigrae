"""A pre-call withdrawal cannot leave or revive an uncertain call permission."""

from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from tests.engine.services.test_native_participant_invocation import (
    begin,
    compiled_native,
    install_workload,
    launched,
    native_action,
    tenant,
)

__all__ = ["compiled_native", "install_workload", "launched", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def withdraw(item, *, attempt_id=None):
    from engine.services import withdraw_native_power_invocation

    withdraw_native_power_invocation(
        operation_id=item.operation,
        member_ref="provision.node.web#0",
        attempt_id=attempt_id or item.attempt_id,
        token=SecretStr("fixture.bound.token"),
    )


@pytest.mark.parametrize("acquired", [False, True])
def test_authenticated_pre_call_withdrawal_fences_the_original_member_slot(launched, acquired):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from engine.services import begin_prepared_native_power_invocation, prepare_native_power_invocation
    from shared.native_participant import native_power_invocation_id

    prepared = prepare_native_power_invocation(
        action_id=UUID(launched.action.action_id),
        member_ref="provision.node.web#0",
        control_cut_digest=launched.action.control_cut_digest,
        token=SecretStr("fixture.bound.token"),
        attempt_id=launched.attempt_id,
    )
    if acquired:
        begin_prepared_native_power_invocation(prepared)
    withdraw(launched)
    slot = ParticipantPowerInvocation.objects.get(
        pk=native_power_invocation_id(launched.operation, "provision.node.web#0"),
    )
    assert slot.attempt_id == launched.attempt_id
    assert slot.closed_at is not None
    assert slot.permission_issued is acquired
    assert slot.container_id == "containerd://synthetic-container"
    assert ParticipantPowerReservation.objects.get(action_id=launched.action.action_id).fenced_at is not None
    launched.case.row.refresh_from_db()
    assert launched.case.row.status == "failed"
    assert launched.case.row.provisioner_operation_id is None
    with pytest.raises(ValueError):
        begin_prepared_native_power_invocation(prepared)
    withdraw(launched)


def test_a_new_attempt_cannot_withdraw_an_existing_uncertain_call(launched):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation

    grant = begin(launched)
    with pytest.raises(ValueError):
        withdraw(launched, attempt_id=uuid4())
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    assert ParticipantPowerReservation.objects.get(action_id=launched.action.action_id).fenced_at is None
    launched.case.row.refresh_from_db()
    assert launched.case.row.status in {"pausing", "resuming"}


def test_pre_call_withdrawal_survives_initiating_policy_revocation(launched):
    from engine.models import ParticipantPowerInvocation

    launched.case.actor.policy_principals.clear()
    withdraw(launched)
    assert ParticipantPowerInvocation.objects.get().closed_at is not None


def test_pre_call_withdrawal_and_status_roll_back_when_strict_audit_fails(launched, monkeypatch):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from engine.services import _native_participant_settlement as service

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(service, "audit_log", unavailable)
    with pytest.raises(RuntimeError):
        withdraw(launched)
    assert not ParticipantPowerInvocation.objects.exists()
    assert ParticipantPowerReservation.objects.get(action_id=launched.action.action_id).fenced_at is None
    launched.case.row.refresh_from_db()
    assert launched.case.row.status in {"pausing", "resuming"}
    assert launched.case.row.provisioner_operation_id == launched.operation
