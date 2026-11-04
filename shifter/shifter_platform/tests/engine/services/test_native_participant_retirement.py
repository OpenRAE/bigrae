"""Independent native teardown contains a range without faking call cessation."""

from uuid import uuid4

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
from tests.engine.services.test_native_warm_retirement import _apply_result

__all__ = ["compiled_native", "install_workload", "launched", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def destroy(item):
    from engine.models import ProvisionerLaunchIntent
    from engine.services import commit_prepared_range_lifecycle, prepare_range_lifecycle

    prepared = prepare_range_lifecycle(item.case.credential, item.case.request_id, "destroy")
    assert commit_prepared_range_lifecycle(prepared)
    item.case.row.refresh_from_db()
    return ProvisionerLaunchIntent.objects.get(operation_id=item.case.row.provisioner_operation_id)


def verify_cleanup(intent):
    from shared.operation_results import ResultStep

    _apply_result(
        intent,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {
            "raes_status": "succeeded",
            "cleanup_inventory": {
                "outcome": "VERIFIED_ABSENT",
                "scope": {"provider": "synthetic"},
                "residual_categories": [],
            },
        },
    )


def test_authorized_teardown_fences_power_without_waiting_for_a_cloud_call_or_reassigning_custody(launched):
    from django.db import IntegrityError, transaction

    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range

    grant = begin(launched)
    original_generation = launched.case.row.resource_generation
    intent = destroy(launched)
    assert intent.payload["operation"] == "destroy"
    assert intent.operation_id != grant.operation_id
    assert launched.case.row.status == "destroying"
    assert launched.case.row.resource_generation == original_generation
    assert ParticipantPowerReservation.objects.get(action_id=launched.action.action_id).fenced_at is not None
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    with pytest.raises(IntegrityError), transaction.atomic():
        Range.objects.filter(pk=launched.case.row.pk).update(resource_generation=uuid4())
    with pytest.raises(ValueError):
        begin(launched)
    finish(launched, grant.invocation_id)
    launched.case.row.refresh_from_db()
    assert launched.case.row.status == "destroying"
    assert launched.case.row.provisioner_operation_id == intent.operation_id


@pytest.mark.parametrize("proof", ["logical", "wrong-operation", "verified"])
def test_verified_world_retirement_releases_only_the_owner_and_retains_native_permission_history(launched, proof):
    from django.db import IntegrityError, transaction
    from django.db.models.deletion import ProtectedError
    from django.utils import timezone

    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation, Range
    from engine.services import native_participant_power_requires_exclusion, native_participant_power_unresolved
    from engine.services._cleanup_verification import record_cleanup_verification

    grant = begin(launched)
    intent = destroy(launched)
    if proof == "verified":
        verify_cleanup(intent)
    else:
        Range.objects.filter(pk=launched.case.row.pk).update(status="destroyed")
        if proof == "wrong-operation":
            record_cleanup_verification(
                request_id=launched.case.request_id,
                operation_id=uuid4(),
                outcome="VERIFIED_ABSENT",
                scope={"provider": "synthetic"},
                residual_categories=[],
                observed_at=timezone.now(),
            )
    assert native_participant_power_unresolved(launched.action.coordinates)
    assert native_participant_power_requires_exclusion(launched.action.coordinates) is (proof != "verified")
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None
    for model in (ParticipantPowerInvocation, ParticipantPowerReservation):
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.all().delete()
    with pytest.raises(ProtectedError):
        Range.objects.filter(pk=launched.case.row.pk).delete()
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None


def test_teardown_audit_failure_restores_the_original_operation_and_power_fences(launched, monkeypatch):
    from unittest.mock import Mock

    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation

    grant = begin(launched)
    monkeypatch.setattr(
        "engine.services._principal_lifecycle.audit_log", Mock(side_effect=RuntimeError("audit unavailable"))
    )
    with pytest.raises(RuntimeError):
        destroy(launched)
    launched.case.row.refresh_from_db()
    assert launched.case.row.provisioner_operation_id == grant.operation_id
    assert launched.case.row.status in {"pausing", "resuming"}
    assert ParticipantPowerReservation.objects.get(action_id=launched.action.action_id).fenced_at is None
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is None


def test_exact_provider_completion_after_teardown_cannot_overwrite_destruction(launched, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from engine.models import ParticipantPowerInvocation
    from engine.services._native_participant_recovery import reconcile_native_power_invocation

    grant = begin(launched)
    intent = destroy(launched)
    launched.job.status.failed = 1
    observer = SimpleNamespace(
        completed_call=Mock(return_value="projects/synthetic/zones/test/operations/operation-one")
    )
    monkeypatch.setattr("shared.cloud.get_native_power_observer", lambda: observer)
    assert reconcile_native_power_invocation(grant.invocation_id)
    assert ParticipantPowerInvocation.objects.get(pk=grant.invocation_id).closed_at is not None
    launched.case.row.refresh_from_db()
    assert launched.case.row.status == "destroying"
    assert launched.case.row.provisioner_operation_id == intent.operation_id
