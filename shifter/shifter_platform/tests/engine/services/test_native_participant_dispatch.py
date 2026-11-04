"""Only the current committed admission can release held native work."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from tests.engine.services.test_native_participant_reservation import _reserve, compiled_native, native_action, tenant

__all__ = ["compiled_native", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def _admit(case, action):
    from engine.services._native_participant_power import record_native_participant_admission

    portable = uuid4()
    record_native_participant_admission(
        case.credential,
        UUID(action.action_id),
        portable_operation_uuid=portable,
        control_cut_digest=action.control_cut_digest,
    )
    return portable


def _release(case, action, portable):
    from engine.services._native_participant_dispatch import release_native_participant_power

    return release_native_participant_power(
        case.credential,
        UUID(action.action_id),
        portable_operation_uuid=portable,
        control_cut_digest=action.control_cut_digest,
    )


def test_committed_current_admission_releases_exact_operation_once(native_action):
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from engine.models import ProvisionerLaunchIntent

    case, action = native_action
    operation = _reserve(case, action)
    portable = _admit(case, action)
    assert _release(case, action, portable) == operation
    assert _release(case, action, portable) == operation
    intent = ProvisionerLaunchIntent.objects.get(operation_id=operation)
    assert intent.status == "PENDING"
    assert Command._claim_next(intent_id=intent.intent_id).operation_id == operation


@pytest.mark.parametrize("fault", ["uncommitted", "receipt", "cut", "authority", "generation", "operation"])
def test_invalidated_admission_keeps_work_unclaimable(native_action, fault):
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from engine.models import ProvisionerLaunchIntent

    case, action = native_action
    operation = _reserve(case, action)
    portable = uuid4() if fault == "uncommitted" else _admit(case, action)
    if fault == "receipt":
        portable = uuid4()
    elif fault == "cut":
        action = replace(action, control_cut_digest="sha256:" + "e" * 64)
    elif fault == "authority":
        case.actor.policy_principals.clear()
    elif fault == "generation":
        case.row.resource_generation = uuid4()
        case.row.save(update_fields=["resource_generation"])
    elif fault == "operation":
        case.row.provisioner_operation_id = uuid4()
        case.row.save(update_fields=["provisioner_operation_id"])
    with pytest.raises((ValueError, PermissionError)):
        _release(case, action, portable)
    intent = ProvisionerLaunchIntent.objects.get(operation_id=operation)
    assert intent.status == "HELD"
    assert Command._claim_next(intent_id=intent.intent_id) is None


def test_failed_release_audit_rolls_back_dispatch_permission(native_action, monkeypatch):
    from engine.models import ProvisionerLaunchIntent
    from engine.services import _native_participant_dispatch

    case, action = native_action
    operation = _reserve(case, action)
    portable = _admit(case, action)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic release audit unavailable")

    monkeypatch.setattr(_native_participant_dispatch, "audit_log", unavailable)
    with pytest.raises(RuntimeError, match="release audit unavailable"):
        _release(case, action, portable)
    assert ProvisionerLaunchIntent.objects.get(operation_id=operation).status == "HELD"
