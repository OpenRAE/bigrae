"""Native member readback must match the exact immutable lifecycle operation."""

from copy import deepcopy
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import OperationInput, OperationResultDisposition, OperationResultInbox, Range, Request
from engine.operation_inputs import operation_input_payload
from engine.services import apply_pending_operation_results
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for
from shared.raes.power_input import parse_native_power_input

pytestmark = pytest.mark.django_db


@pytest.fixture
def native_correlation_state(request):
    return getattr(request, "param", {"grants": 2, "closed": True, "released": True})


@pytest.fixture(params=["pause", "resume"])
def operation(request, native_correlation_state):
    verb = request.param
    request_id, operation_id = uuid4(), uuid4()
    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    source = Request.objects.create(request_id=request_id, request_type="range", user=user)
    plan = {
        "kind": "raes_provisioning_plan",
        "resources": {
            "provision.node.web": {
                "address": "provision.node.web",
                "resource_type": "node",
                "payload": {"count": 2},
            }
        },
    }
    members = [
        {
            "uuid": f"provision.node.web#{index}",
            "instance_id": f"synthetic-web-{index}",
            "status": "ready" if verb == "pause" else "paused",
            "native_power_target": {
                "backend": "gce",
                "project_id": "synthetic-project",
                "zone": "europe-west3-a",
                "instance_name": f"synthetic-web-{index}",
                "bootstrap_capability": "standard",
            },
            "native_power_incarnation": {
                "instance_identity": str(100 + index),
                "disks": [{"name": f"synthetic-web-{index}-boot", "identity": str(200 + index)}],
            },
        }
        for index in range(2)
    ]
    row = Range.objects.create(
        request=source,
        user=user,
        workspace_id=1,
        range_config=plan,
        range_backend="gce",
        provisioner_operation_id=operation_id,
        resource_generation=uuid4(),
        status="pausing" if verb == "pause" else "resuming",
        provisioned_instances=members,
    )
    from django.utils import timezone

    from engine.models import (
        ParticipantPowerInvocation,
        ParticipantPowerReservation,
        ProvisionerLaunchIntent,
        RaesCompilerInputBinding,
    )
    from shared.native_participant import native_power_invocation_id
    from shared.raes.operation_input import RaesInputBindings, RaesRangeIdentity, build_raes_operation_input

    original_id = uuid4()
    original = build_operation_envelope(
        operation_id=original_id,
        request_id=request_id,
        resource="raes-range",
        operation="provision",
        payload=build_raes_operation_input(
            plan=plan,
            bindings=RaesInputBindings(delivery=[]),
            image_candidates={},
            range_backend="gce",
            instantiation_purpose="live_fire",
            identity=RaesRangeIdentity(row.pk, str(row.resource_generation)),
        ),
    )
    OperationInput.objects.create(
        operation_id=original_id,
        request_id=request_id,
        resource="raes-range",
        operation="provision",
        contract_version=original["contract_version"],
        envelope=original,
    )
    compiler = RaesCompilerInputBinding.objects.create(
        range=row,
        resource_generation=row.resource_generation,
        scope_digest="sha256:" + "a" * 64,
        source_package_digest="sha256:" + "b" * 64,
        compiler_input_digest="sha256:" + "c" * 64,
        raes_version="10.6.0",
    )
    intent = ProvisionerLaunchIntent.objects.create(
        operation_id=operation_id,
        idempotency_key=str(operation_id),
        payload={},
        next_attempt_at=timezone.now(),
    )
    reservation = ParticipantPowerReservation.objects.create(
        launch_intent=intent,
        compiler_binding=compiler,
        run_id=uuid4(),
        participant_address="participant.analyst",
        controller_address="participant.organizer",
        episode_id="episode:synthetic",
        action_id=uuid4(),
        proposal_id=uuid4(),
        approval_uuid=uuid4(),
        meaning_digest="sha256:" + "d" * 64,
        portable_operation_uuid=uuid4(),
        control_cut_digest="sha256:" + "e" * 64,
        released_at=timezone.now() if native_correlation_state["released"] else None,
    )
    for member in members[: native_correlation_state["grants"]]:
        ParticipantPowerInvocation.objects.create(
            invocation_id=native_power_invocation_id(operation_id, member["uuid"]),
            reservation=reservation,
            member_ref=member["uuid"],
            pod_uid="synthetic-pod",
            job_uid="synthetic-job",
            closed_at=timezone.now() if native_correlation_state["closed"] else None,
        )
    payload = operation_input_payload(row, "range", source, operation=verb)
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=request_id,
        resource="range",
        operation=verb,
        payload=payload,
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=request_id,
        resource="range",
        operation=verb,
        contract_version=envelope["contract_version"],
        envelope=envelope,
    )
    return row, verb


def _result(operation, *, terminal=False, failed=False, members=None, generation=None):
    row, verb = operation
    status = "paused" if verb == "pause" else "ready"
    if failed:
        step = ResultStep.RANGE_TERMINAL_FAILED
        payload = {"reason_code": "cloud_operation_failed", "diagnostic": "Native power readback incomplete"}
    elif terminal:
        step = ResultStep.RANGE_TERMINAL_PAUSED if verb == "pause" else ResultStep.RANGE_TERMINAL_READY
        payload = {"status": status}
    else:
        step = ResultStep.RANGE_RAES_MEMBERS_PAUSED if verb == "pause" else ResultStep.RANGE_RAES_MEMBERS_READY
        payload = {
            "resource_generation": str(generation or row.resource_generation),
            "members": [
                {"member_ref": ref, "status": status}
                for ref in (members if members is not None else ["provision.node.web#0", "provision.node.web#1"])
            ],
        }
    envelope = build_operation_envelope(
        operation_id=row.provisioner_operation_id,
        request_id=row.request.request_id,
        resource="range",
        operation=verb,
        payload=payload,
    )
    digest = canonical_payload_digest(payload)
    return OperationResultInbox.objects.create(
        operation_id=row.provisioner_operation_id,
        request_id=row.request.request_id,
        resource="range",
        operation=verb,
        contract_version=envelope["contract_version"],
        result_kind=result_kind_for("range", verb, step=step),
        result_step=step,
        result_identity=build_result_identity(operation_id=row.provisioner_operation_id, step=step, digest=digest),
        payload_digest=digest,
        envelope=envelope,
    )


def test_native_input_materializes_detached_realized_targets(operation):
    row, _ = operation
    stored = OperationInput.objects.get(operation_id=row.provisioner_operation_id)
    power = parse_native_power_input(stored.envelope["payload"]["native_power"], plan=row.range_config)
    assert power.resource_generation == row.resource_generation
    assert {member.member_ref for member in power.members} == {member["uuid"] for member in row.provisioned_instances}


def test_complete_observed_members_allow_terminal_state(operation):
    row, verb = operation
    observed, terminal = _result(operation), _result(operation, terminal=True)
    apply_pending_operation_results()
    row.refresh_from_db()
    observed.refresh_from_db()
    terminal.refresh_from_db()
    expected = "paused" if verb == "pause" else "ready"
    assert observed.disposition == terminal.disposition == OperationResultDisposition.APPLIED
    assert row.status == expected
    assert all(member["status"] == expected for member in row.provisioned_instances)


@pytest.mark.parametrize(
    "native_correlation_state",
    [
        {"grants": 1, "closed": True, "released": True},
        {"grants": 2, "closed": False, "released": True},
        {"grants": 2, "closed": True, "released": False},
    ],
    indirect=True,
    ids=["missing-grant", "open-grant", "unreleased"],
)
def test_complete_member_assertions_cannot_replace_native_invocation_completion(operation):
    row, _ = operation
    _result(operation)
    terminal = _result(operation, terminal=True)
    apply_pending_operation_results()
    terminal.refresh_from_db()
    row.refresh_from_db()
    assert terminal.disposition == OperationResultDisposition.REJECTED_INVALID
    assert row.status in {"pausing", "resuming"}


@pytest.mark.parametrize(
    "native_correlation_state",
    [
        {"grants": 2, "closed": False, "released": True},
    ],
    indirect=True,
)
def test_unknown_native_failure_retains_its_operation_identity_and_exclusion(operation):
    row, _ = operation
    original_operation = row.provisioner_operation_id
    failed = _result(operation, failed=True)
    apply_pending_operation_results()
    failed.refresh_from_db()
    row.refresh_from_db()
    assert failed.disposition == OperationResultDisposition.APPLIED
    assert row.status == "failed"
    assert row.provisioner_operation_id == original_operation


def test_partial_readback_is_preserved_but_cannot_settle_the_range(operation):
    row, verb = operation
    observed = _result(operation, members=["provision.node.web#0"])
    terminal = _result(operation, terminal=True)
    apply_pending_operation_results()
    row.refresh_from_db()
    observed.refresh_from_db()
    terminal.refresh_from_db()
    assert observed.disposition == OperationResultDisposition.APPLIED
    assert terminal.disposition != OperationResultDisposition.APPLIED
    assert row.status == ("pausing" if verb == "pause" else "resuming")
    assert row.provisioned_instances[0]["status"] == ("paused" if verb == "pause" else "ready")
    assert row.provisioned_instances[1]["status"] == ("ready" if verb == "pause" else "paused")


def test_terminal_without_this_operations_member_readback_is_refused(operation):
    result = _result(operation, terminal=True)
    apply_pending_operation_results()
    result.refresh_from_db()
    assert result.disposition != OperationResultDisposition.APPLIED


def test_partial_observations_survive_terminal_failure(operation):
    row, verb = operation
    observed = _result(operation, members=["provision.node.web#0"])
    failure = _result(operation, failed=True)
    apply_pending_operation_results()
    row.refresh_from_db()
    observed.refresh_from_db()
    failure.refresh_from_db()
    assert observed.disposition == failure.disposition == OperationResultDisposition.APPLIED
    assert row.status == "failed"
    assert row.provisioned_instances[0]["status"] == ("paused" if verb == "pause" else "ready")
    assert row.provisioned_instances[1]["status"] == ("ready" if verb == "pause" else "paused")


@pytest.mark.parametrize(
    "fault",
    [
        "generation",
        "member",
        "target",
        "incarnation",
        "input-missing",
        "input-identity",
        "range-generation",
    ],
)
def test_foreign_or_stale_power_readback_cannot_change_members(operation, fault):
    row, _ = operation
    original = deepcopy(row.provisioned_instances)
    if fault == "target":
        row.provisioned_instances[0]["native_power_target"]["instance_name"] = "replaced-web"
        row.save(update_fields=["provisioned_instances"])
        original = deepcopy(row.provisioned_instances)
    elif fault == "incarnation":
        row.provisioned_instances[0]["native_power_incarnation"]["instance_identity"] = "999"
        row.save(update_fields=["provisioned_instances"])
        original = deepcopy(row.provisioned_instances)
    elif fault == "input-missing":
        OperationInput.objects.filter(operation_id=row.provisioner_operation_id).delete()
    elif fault == "input-identity":
        OperationInput.objects.filter(operation_id=row.provisioner_operation_id).update(request_id=uuid4())
    elif fault == "range-generation":
        row.resource_generation = uuid4()
        row.save(update_fields=["resource_generation"])
    result = _result(
        operation,
        generation=uuid4() if fault == "generation" else None,
        members=["provision.node.foreign#0"] if fault == "member" else None,
    )
    apply_pending_operation_results()
    row.refresh_from_db()
    result.refresh_from_db()
    assert result.disposition != OperationResultDisposition.APPLIED
    assert row.provisioned_instances == original


def test_audit_failure_rolls_back_native_member_observations(operation):
    from shared.audit import bind_audit_writer, get_audit_writer, reset_audit_writer

    row, _ = operation
    original = deepcopy(row.provisioned_instances)
    result = _result(operation)

    class UnavailableAudit:
        def write(self, event):
            raise RuntimeError("Synthetic audit failure")

    writer = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(UnavailableAudit())
    try:
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            apply_pending_operation_results()
    finally:
        reset_audit_writer()
        bind_audit_writer(writer)
    row.refresh_from_db()
    result.refresh_from_db()
    assert result.disposition == OperationResultDisposition.PENDING
    assert row.provisioned_instances == original
