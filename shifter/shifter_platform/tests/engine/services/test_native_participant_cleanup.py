"""Owning SDK settlement fences delivery without erasing uncertain effects."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from tests.engine.services.test_native_participant_dispatch import _admit, _release
from tests.engine.services.test_native_participant_invocation import (
    begin,
    compiled_native,
    launched,
    native_action,
    tenant,
)
from tests.engine.services.test_native_participant_reservation import _reserve

__all__ = ["compiled_native", "launched", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def fence(action):
    from engine.services import fence_native_participant_dispatch

    fence_native_participant_dispatch(UUID(action.action_id), action.coordinates)


@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_never_invoked_work_restores_the_actual_prior_status_and_cannot_revive(native_action, released, failed):
    from engine.models import ParticipantPowerReservation

    case, action = native_action
    if failed:
        case.row.status = "failed"
        case.row.save(update_fields=["status"])
    previous = case.row.status
    _reserve(case, action)
    portable = _admit(case, action)
    if released:
        _release(case, action, portable)
    fence(action)
    fence(action)
    case.row.refresh_from_db()
    assert case.row.status == previous
    assert case.row.provisioner_operation_id is None
    assert ParticipantPowerReservation.objects.get(action_id=action.action_id).fenced_at is not None
    for retry in (
        lambda: _reserve(case, action),
        lambda: _admit(case, action),
        lambda: _release(case, action, portable),
    ):
        with pytest.raises(ValueError):
            retry()


def test_revoked_authority_and_unavailable_private_key_do_not_block_no_effect_cleanup(native_action, settings):
    from cryptography.fernet import Fernet

    case, action = native_action
    previous = case.row.status
    _reserve(case, action)
    case.actor.is_active = False
    case.actor.save(update_fields=["is_active"])
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    fence(action)
    case.row.refresh_from_db()
    assert case.row.status == previous


@pytest.mark.parametrize("fault", ["generation", "run", "scope"])
def test_cleanup_refuses_changed_native_context(native_action, fault):
    from engine.models import ParticipantPowerReservation

    case, action = native_action
    _reserve(case, action)
    if fault == "generation":
        action = replace(action, coordinates=replace(action.coordinates, resource_generation=uuid4()))
    elif fault == "run":
        action = replace(action, coordinates=replace(action.coordinates, run_id=uuid4()))
    else:
        case.row.owner_principal_uuid = uuid4()
        case.row.save(update_fields=["owner_principal_uuid"])
    with pytest.raises(ValueError):
        fence(action)
    assert ParticipantPowerReservation.objects.get(action_id=action.action_id).fenced_at is None


def test_audit_failure_rolls_back_the_fence_and_native_status(native_action, monkeypatch):
    from engine.models import ParticipantPowerReservation

    case, action = native_action
    operation = _reserve(case, action)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic settlement audit unavailable")

    monkeypatch.setattr("engine.services._native_participant_cleanup.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="settlement audit unavailable"):
        fence(action)
    case.row.refresh_from_db()
    assert case.row.provisioner_operation_id == operation
    assert case.row.status in {"pausing", "resuming"}
    assert ParticipantPowerReservation.objects.get(action_id=action.action_id).fenced_at is None


def test_issued_call_is_never_erased_or_reclassified_as_no_effect(launched):
    from engine.models import ParticipantPowerInvocation

    grant = begin(launched)
    fence(launched.action)
    launched.case.row.refresh_from_db()
    assert launched.case.row.status == "failed"
    assert launched.case.row.provisioner_operation_id == launched.operation
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    with pytest.raises(ValueError):
        begin(launched)
