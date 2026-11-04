"""Recovery fences failed native work; only exact call cessation clears exclusion."""

from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from tests.engine.services.test_native_participant_invocation import (
    begin,
    compiled_native,
    finish,
    install_workload,
    launched,
    native_action,
    tenant,
)

__all__ = ["compiled_native", "install_workload", "launched", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.fixture
def observed(launched, monkeypatch):
    grant = begin(launched)
    observer = NS(completed_call=Mock(return_value="projects/synthetic/zones/test/operations/operation-one"))
    monkeypatch.setattr("shared.cloud.get_native_power_observer", lambda: observer)
    return launched, grant, observer


def test_healthy_worker_keeps_its_readback_and_readiness_window(observed):
    from engine.services._native_participant_recovery import reconcile_native_power_invocation

    item, grant, observer = observed
    assert not reconcile_native_power_invocation(grant.invocation_id)
    observer.completed_call.assert_not_called()
    item.case.row.refresh_from_db()
    assert item.case.row.status in {"pausing", "resuming"}


@pytest.mark.parametrize("trigger", ["failed", "inactive", "deadline"])
def test_failed_work_closes_only_exact_completed_call_and_never_reports_success(observed, trigger, monkeypatch):
    from django.utils import timezone

    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from engine.services import native_participant_power_unresolved
    from engine.services._native_participant_recovery import reconcile_native_power_invocation

    item, grant, observer = observed
    if trigger == "failed":
        item.case.row.status = "failed"
        item.case.row.save(update_fields=["status"])
    elif trigger == "inactive":
        item.job.status.failed = 1
    else:
        later = timezone.now() + timedelta(minutes=31)
        monkeypatch.setattr(timezone, "now", lambda: later)
    item.case.actor.policy_principals.clear()
    assert reconcile_native_power_invocation(grant.invocation_id)
    observer.completed_call.assert_called_once_with(grant)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is not None
    assert ParticipantPowerReservation.objects.get(action_id=item.action.action_id).fenced_at is not None
    assert not native_participant_power_unresolved(item.action.coordinates)
    item.case.row.refresh_from_db()
    assert item.case.row.status == "failed"
    assert item.case.row.provisioner_operation_id is None
    assert not reconcile_native_power_invocation(grant.invocation_id)


def test_inactive_job_without_exact_provider_completion_keeps_the_original_exclusion(observed):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from engine.services import native_participant_power_unresolved
    from engine.services._native_participant_recovery import reconcile_native_power_invocation

    item, grant, observer = observed
    item.job.metadata.deletion_timestamp = "now"
    observer.completed_call.return_value = None
    assert not reconcile_native_power_invocation(grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    assert ParticipantPowerReservation.objects.get(action_id=item.action.action_id).fenced_at is not None
    assert native_participant_power_unresolved(item.action.coordinates)
    item.case.row.refresh_from_db()
    assert item.case.row.status == "failed"
    assert item.case.row.provisioner_operation_id == item.operation
    with pytest.raises(ValueError):
        begin(item)


def test_completion_during_observation_is_idempotent_and_does_not_replace_current_native_work(observed):
    from engine.services._native_participant_recovery import reconcile_native_power_invocation

    item, grant, observer = observed
    item.case.row.status = "failed"
    item.case.row.save(update_fields=["status"])

    def completed(_grant):
        finish(item, grant.invocation_id)
        return "projects/synthetic/zones/test/operations/operation-one"

    observer.completed_call.side_effect = completed
    assert not reconcile_native_power_invocation(grant.invocation_id)


def test_recovery_fence_rolls_back_if_its_strict_audit_is_unavailable(observed, monkeypatch):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from engine.services import _native_participant_recovery as service

    item, grant, observer = observed
    item.job.status.failed = 1
    monkeypatch.setattr(service, "audit_log", Mock(side_effect=RuntimeError("synthetic audit unavailable")))
    with pytest.raises(RuntimeError):
        service.reconcile_native_power_invocation(grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    assert ParticipantPowerReservation.objects.get(action_id=item.action.action_id).fenced_at is None
    observer.completed_call.assert_not_called()


def test_recovery_batch_rotates_past_an_unknown_record_and_rejects_unbounded_scans(observed, monkeypatch):
    from engine.services import _native_participant_recovery as service

    _item, grant, _observer = observed
    reconcile = Mock(return_value=False)
    monkeypatch.setattr(service, "reconcile_native_power_invocation", reconcile)
    first = service.reconcile_native_power_invocations(limit=1)
    assert first.cursor == grant.invocation_id
    assert (first.examined, first.settled) == (1, 0)
    empty = service.reconcile_native_power_invocations(cursor=first.cursor, limit=1)
    assert empty.cursor is None and empty.examined == 0
    assert service.reconcile_native_power_invocations(cursor=empty.cursor, limit=1).examined == 1
    assert reconcile.call_count == 2
    for limit in (0, 33, True):
        with pytest.raises(ValueError):
            service.reconcile_native_power_invocations(limit=limit)
