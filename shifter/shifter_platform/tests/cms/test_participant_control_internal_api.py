"""Private HTTP grant delivery uses live workload proof and no browser fallback."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from tests.cms.test_participant_control_binding import controlled_pack, controlled_source, product_range, tenant
from tests.ctf.test_participant_control_api import bind, installed_worker

__all__ = ["controlled_pack", "controlled_source", "installed_worker", "product_range", "tenant"]
pytestmark = pytest.mark.django_db(transaction=True)
_PUBLIC = "/api/v1/participant-control/ctf"
_PRIVATE = "/internal/participant-control/invocations"


def test_private_grant_protocol_requires_exact_job_and_allows_revoked_worker_cessation(
    installed_worker, settings, monkeypatch
):
    from engine.models import ParticipantPowerInvocation, ParticipantPowerReservation
    from tests.engine.services.test_native_participant_invocation import install_workload

    settings.ROOT_URLCONF = "config.participant_control_worker_urls"
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "synthetic-native-provisioner"
    item = installed_worker
    human = APIClient()
    human.force_login(item.case.actor)
    response = bind(human, item)
    assert response.status_code == 201, response.json()
    binding_id = response.json()["binding_id"]
    proposal, action = uuid4(), uuid4()
    for kind in ("proposal", "approval", "action"):
        current = human.get(f"{_PUBLIC}/bindings/{binding_id}/")
        assert current.status_code == 200, current.json()
        response = human.post(
            f"{_PUBLIC}/bindings/{binding_id}/commands/",
            {
                "request_id": str(proposal if kind == "proposal" else action if kind == "action" else uuid4()),
                "kind": kind,
                "verb": "pause",
                "proposal_id": str(proposal),
                "action_id": str(action),
                "expected_cut_digest": current.json()["control_cut_digest"],
            },
            format="json",
        )
        assert response.status_code == 200 and response.json()["state"] == "succeeded", response.json()
    reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
    workload = install_workload(item.case, None, reservation.launch_intent.operation_id, monkeypatch)
    body = {
        "attempt_id": str(uuid4()),
        "operation_id": str(reservation.launch_intent.operation_id),
        "member_ref": "provision.node.web#0",
    }
    assert human.post(f"{_PRIVATE}/begin/", body, format="json").status_code == 403
    assert not ParticipantPowerInvocation.objects.exists()
    machine = APIClient()
    machine.credentials(HTTP_AUTHORIZATION="Bearer fixture.bound.token")
    workload.authentication.create_token_review.return_value.status.audiences = ["foreign-audience"]
    assert machine.post(f"{_PRIVATE}/begin/", body, format="json").status_code == 403
    assert not ParticipantPowerInvocation.objects.exists()
    workload.authentication.create_token_review.return_value.status.audiences = [
        "shifter-native-participant-invocation"
    ]
    granted = machine.post(f"{_PRIVATE}/begin/", body, format="json")
    assert granted.status_code == 200, granted.json()
    assert granted.json()["contract_version"] == "shifter-native-power-grant/v1"
    assert granted.json()["operation_id"] == body["operation_id"]
    assert machine.post(f"{_PRIVATE}/begin/", body, format="json").status_code == 403
    assert ParticipantPowerInvocation.objects.count() == 1
    item.case.actor.policy_principals.clear()
    finished = machine.post(
        f"{_PRIVATE}/finish/",
        {"invocation_id": granted.json()["invocation_id"], "attempt_id": body["attempt_id"]},
        format="json",
    )
    assert finished.status_code == 204
    assert ParticipantPowerInvocation.objects.get().closed_at is not None
    assert (
        machine.post(
            f"{_PRIVATE}/finish/",
            {"invocation_id": granted.json()["invocation_id"], "attempt_id": body["attempt_id"]},
            format="json",
        ).status_code
        == 204
    )
    # Actual principal-aware inputs use v2 authority envelopes. The incumbent
    # provisioner result writer emits v1: the real applier must accept the
    # shared operation identity rather than require equal transport versions.
    from engine.models import OperationInput, OperationResultDisposition, OperationResultInbox
    from engine.services import apply_pending_operation_results
    from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
    from shared.operation_results import ResultStep, build_result_identity, result_kind_for

    operation_id = reservation.launch_intent.operation_id
    stored = OperationInput.objects.get(operation_id=operation_id)
    assert stored.contract_version == "2"
    rows = []
    for step, payload in (
        (
            ResultStep.RANGE_RAES_MEMBERS_PAUSED,
            {
                "resource_generation": str(item.case.row.resource_generation),
                "members": [
                    {"member_ref": "provision.node.web#0", "status": "paused"},
                ],
            },
        ),
        (ResultStep.RANGE_TERMINAL_PAUSED, {"status": "paused"}),
    ):
        envelope = build_operation_envelope(
            operation_id=operation_id,
            request_id=item.case.request_id,
            resource="range",
            operation="pause",
            payload=payload,
        )
        assert envelope["contract_version"] == "1"
        digest = canonical_payload_digest(payload)
        rows.append(
            OperationResultInbox.objects.create(
                operation_id=operation_id,
                request_id=item.case.request_id,
                resource="range",
                operation="pause",
                contract_version=envelope["contract_version"],
                result_kind=result_kind_for("range", "pause", step=step),
                result_step=step,
                result_identity=build_result_identity(operation_id=operation_id, step=step, digest=digest),
                payload_digest=digest,
                envelope=envelope,
            )
        )
    apply_pending_operation_results()
    item.case.row.refresh_from_db()
    assert item.case.row.status == "paused"
    for row in rows:
        row.refresh_from_db()
        assert row.disposition == OperationResultDisposition.APPLIED
