"""Current native destroy proof releases custody in the result transaction only."""

from uuid import uuid4

import pytest

from engine.models import GcpRangeProjectUse, OperationInput, RangeCleanupVerification
from engine.services import apply_pending_operation_results
from shared.operation_results import ResultStep
from tests.engine.services.test_gcp_range_projects import bind
from tests.engine.services.test_gcp_range_projects import registration as registration
from tests.engine.services.test_operation_apply_raes import _Fixture
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def destroy_result(registration, *, change=None, outcome="VERIFIED_ABSENT"):
    fx = _Fixture(operation="destroy", status="destroying")
    use = bind(registration, fx.range)
    digest = use.binding["baseline"]["state_digest"]
    proof = {
        "lease_id": str(use.pk),
        "registration_id": str(registration.pk),
        "baseline_state_digest": digest,
        "observed_state_digest": digest,
        "outcome": "restored",
    }
    proofs = [proof]
    if change == "missing":
        proofs = []
    elif change == "extra":
        proofs.append({**proof, "lease_id": str(uuid4())})
    elif change == "duplicate":
        proofs.append(proof)
    elif change == "digest":
        proof["observed_state_digest"] = "sha256:" + "f" * 64
    elif change == "registration":
        proof["registration_id"] = str(uuid4())
    elif change == "lease":
        proof["lease_id"] = str(uuid4())
    row = fx.seed(
        ResultStep.RAES_TERMINAL_DESTROYED,
        {
            "raes_status": "succeeded",
            "cleanup_inventory": {
                "outcome": outcome,
                "residual_categories": [],
                "scope": {"gcp_projects": proofs},
            },
        },
    )
    OperationInput.objects.create(
        operation_id=fx.operation_id,
        request_id=fx.request_id,
        resource="raes-range",
        operation="provision" if change == "input-operation" else "destroy",
        contract_version=row.contract_version,
        envelope={
            **row.envelope,
            "operation": "provision" if change == "input-operation" else "destroy",
            "payload": {},
        },
    )
    return fx, use, row


def test_current_destroy_applies_before_release_and_commits_both_together(registration):
    fx, use, receipt = destroy_result(registration)
    assert apply_pending_operation_results() == 1
    use.refresh_from_db()
    receipt.refresh_from_db()
    fx.range.refresh_from_db()
    assert (fx.range.status, receipt.disposition) == ("destroyed", "APPLIED")
    assert use.released_at is not None and use.release_operation_id == receipt.operation_id
    assert use.release_state_digest == use.binding["baseline"]["state_digest"]


@pytest.mark.parametrize(
    "change", ["missing", "extra", "duplicate", "digest", "registration", "lease", "input-operation"]
)
def test_incomplete_or_wrong_project_proof_cannot_claim_global_absence(registration, change):
    fx, use, receipt = destroy_result(registration, change=change)
    assert apply_pending_operation_results() == 1
    use.refresh_from_db()
    receipt.refresh_from_db()
    fx.range.refresh_from_db()
    assert (fx.range.status, receipt.disposition) == ("destroying", "REJECTED_INVALID")
    assert use.released_at is None
    assert not RangeCleanupVerification.objects.filter(operation_id=receipt.operation_id).exists()


def test_logical_destroy_with_incomplete_inventory_keeps_project_held(registration):
    fx, use, receipt = destroy_result(registration, change="missing", outcome="INCOMPLETE")
    assert apply_pending_operation_results() == 1
    use.refresh_from_db()
    receipt.refresh_from_db()
    fx.range.refresh_from_db()
    assert (fx.range.status, receipt.disposition) == ("destroyed", "APPLIED")
    assert use.released_at is None
    assert GcpRangeProjectUse.objects.filter(project=registration, released_at__isnull=True).count() == 1


def test_sql_rejects_destroy_label_when_original_native_operation_was_provision(registration):
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    fx, use, receipt = destroy_result(registration, change="input-operation")
    fx.range.status = "destroyed"
    fx.range.save(update_fields=["status"])
    receipt.disposition = "APPLIED"
    receipt.save(update_fields=["disposition"])
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).update(
            released_at=timezone.now(),
            release_operation_id=receipt.operation_id,
            release_state_digest=use.binding["baseline"]["state_digest"],
        )
