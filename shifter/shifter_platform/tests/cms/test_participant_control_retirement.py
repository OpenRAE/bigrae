"""Native teardown evidence retires routing without a revoked actor's authority."""

from uuid import uuid4

import pytest

from tests.cms.test_participant_control_binding import bind, controlled_pack, controlled_source, product_range, tenant
from tests.engine.services.test_native_participant_retirement import verify_cleanup

__all__ = ["controlled_pack", "controlled_source", "product_range", "tenant"]
pytestmark = pytest.mark.django_db


def queued_destroy(item):
    from engine.models import ProvisionerLaunchIntent
    from engine.services import commit_prepared_range_lifecycle, prepare_range_lifecycle
    from shared.authorization import TargetRef

    prepared = prepare_range_lifecycle(
        item.case.credential,
        item.case.request_id,
        "destroy",
        authority_action="event.manage_ranges",
        authority_target=TargetRef("event", item.event.pk),
    )
    assert commit_prepared_range_lifecycle(prepared)
    item.case.row.refresh_from_db()
    return ProvisionerLaunchIntent.objects.get(operation_id=item.case.row.provisioner_operation_id)


@pytest.mark.parametrize("proof", ["logical", "wrong-operation", "verified"])
def test_binding_retirement_requires_actual_current_generation_cleanup(product_range, proof):
    from django.utils import timezone

    from cms.models import ParticipantControlBinding
    from cms.services import retire_verified_native_participant_control
    from engine.models import Range
    from engine.services import record_cleanup_verification

    item = product_range
    binding = bind(item)
    cleanup = queued_destroy(item)
    if proof == "verified":
        verify_cleanup(cleanup)
    else:
        Range.objects.filter(pk=item.case.row.pk).update(status="destroyed")
        if proof == "wrong-operation":
            record_cleanup_verification(
                request_id=item.case.request_id,
                operation_id=uuid4(),
                outcome="VERIFIED_ABSENT",
                scope={"provider": "synthetic"},
                residual_categories=[],
                observed_at=timezone.now(),
            )
    item.case.actor.policy_principals.clear()
    assert retire_verified_native_participant_control(item.instance.uuid) is (proof == "verified")
    saved = ParticipantControlBinding.objects.get(pk=binding.id)
    assert (saved.invalidated_at is not None) is (proof == "verified")
    assert saved.run_id == binding.coordinates.run_id
    if proof == "verified":
        assert not retire_verified_native_participant_control(item.instance.uuid)


def test_strict_retirement_audit_failure_keeps_current_binding(product_range, monkeypatch):
    from unittest.mock import Mock

    from cms.models import ParticipantControlBinding
    from cms.services import retire_verified_native_participant_control

    item = product_range
    binding = bind(item)
    verify_cleanup(queued_destroy(item))
    monkeypatch.setattr(
        "cms.services._participant_control_retirement.audit_log",
        Mock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError):
        retire_verified_native_participant_control(item.instance.uuid)
    assert ParticipantControlBinding.objects.get(pk=binding.id).invalidated_at is None


def test_duplicate_destroyed_status_retries_routing_retirement_after_verified_evidence(product_range):
    from cms.handlers.range_events import apply_range_status
    from cms.models import ParticipantControlBinding, RangeInstance

    item = product_range
    binding = bind(item)
    cleanup = queued_destroy(item)
    RangeInstance.objects.filter(pk=item.instance.pk).update(status="destroyed")
    item.instance.refresh_from_db()
    assert not apply_range_status(item.instance, "destroyed")
    assert ParticipantControlBinding.objects.get(pk=binding.id).invalidated_at is None
    verify_cleanup(cleanup)
    assert not apply_range_status(item.instance, "destroyed")
    assert ParticipantControlBinding.objects.get(pk=binding.id).invalidated_at is not None
