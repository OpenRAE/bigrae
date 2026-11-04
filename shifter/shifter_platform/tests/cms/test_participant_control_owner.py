"""The installed CMS owner traverses native policy, released crossings and held work."""

from uuid import uuid4

import pytest

from shared.native_participant import NativeControlSubmission
from tests.cms.test_participant_control_binding import bind, controlled_pack, controlled_source, product_range, tenant

__all__ = ["controlled_pack", "controlled_source", "product_range", "tenant"]
pytestmark = pytest.mark.django_db(transaction=True)


def test_binding_initialization_is_one_way_and_lost_store_never_resets_its_run(product_range, tmp_path):
    from django.db import IntegrityError, transaction

    from cms.models import ParticipantControlBinding
    from cms.services._participant_control_owner import open_native_participant_control_owner

    item = product_range
    binding = bind(item)
    root = tmp_path / "runtime"
    root.mkdir()
    assert ParticipantControlBinding.objects.get(pk=binding.id).runtime_initialized_at is None
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=root)
    submit(owner, item.case.credential, "proposal", proposal=uuid4(), action=uuid4())
    expected = owner.cursor(item.case.credential)
    owner.close()
    assert ParticipantControlBinding.objects.get(pk=binding.id).runtime_initialized_at is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        ParticipantControlBinding.objects.filter(pk=binding.id).update(runtime_initialized_at=None)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=root)
    assert owner.cursor(item.case.credential) == expected
    owner.close()
    root.rename(root.with_name("retained-runtime"))
    root.mkdir()
    with pytest.raises(ValueError, match="runtime history unavailable"):
        open_native_participant_control_owner(item.case.credential, binding.id, store_root=root)


def test_compatible_deployment_and_trust_rotation_reopen_the_same_control_history(product_range, tmp_path, settings):
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from shared.participant_control_installation import NativeControlInstallation
    from tests.shared.test_participant_control_installation import synthetic_installation_values

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    submit(owner, item.case.credential, "proposal", proposal=uuid4(), action=uuid4())
    cursor = owner.cursor(item.case.credential)
    owner.close()
    original = settings.PARTICIPANT_CONTROL_INSTALLATION
    replacement = NativeControlInstallation.model_validate(
        {
            **original.model_dump(),
            "owner_image": "example.test/updated-platform@sha256:" + "a" * 64,
            "provisioner_image": "example.test/updated-provisioner@sha256:" + "b" * 64,
            "trust_ca_pem": synthetic_installation_values()["trust_ca_pem"],
        }
    )
    settings.PARTICIPANT_CONTROL_INSTALLATION = replacement
    settings.ENGINE_TASK_DEFINITION = replacement.provisioner_image
    assert replacement.digest != original.digest
    assert replacement.policy_digest == original.policy_digest
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    try:
        assert owner.cursor(item.case.credential) == cursor
        assert bind(item).id == binding.id
    finally:
        owner.close()


def test_changed_control_budgets_cannot_silently_reopen_a_previous_binding(product_range, tmp_path, settings):
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from shared.exceptions import ValidationError
    from shared.participant_control_installation import NativeControlInstallation

    item = product_range
    binding = bind(item)
    original = settings.PARTICIPANT_CONTROL_INSTALLATION
    replacement = NativeControlInstallation.model_validate(
        {
            **original.model_dump(),
            "budgets": {**original.budgets.model_dump(), "admission_ms": 11_000},
        }
    )
    assert replacement.policy_digest != original.policy_digest
    settings.PARTICIPANT_CONTROL_INSTALLATION = replacement
    with pytest.raises(ValidationError):
        open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)


def submit(owner, credential, kind, *, proposal, action, request_id=None, cut=None):
    request_id = request_id or (proposal if kind == "proposal" else action if kind == "action" else uuid4())
    return owner.submit(
        credential,
        submission=NativeControlSubmission(
            request_id=request_id,
            kind=kind,
            verb="pause",
            proposal_id=proposal,
            action_id=action,
            expected_cut_digest=cut or owner.cursor(credential).control_cut_digest,
        ),
    )


def test_installed_owner_records_governed_review_then_releases_exact_native_work(product_range, tmp_path):
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from engine.models import ParticipantPowerReservation

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    proposal, action = uuid4(), uuid4()
    try:
        assert binding.id != binding.coordinates.binding_ref
        for kind in ("proposal", "approval", "action"):
            outcome = submit(owner, item.case.credential, kind, proposal=proposal, action=action)
            status = owner.session._owner.get_operation(str(outcome.operation_id))
            assert outcome.state == "succeeded", (kind, status.diagnostics)
        row = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
        assert row.portable_operation_uuid == outcome.operation_id
        assert row.approval_uuid == ParticipantControlCommand.objects.get(kind="approval").pk
        assert row.released_at is not None
        assert row.launch_intent.status == "PENDING"
        assert row.launch_intent.attempts == 0
        original = ParticipantControlCommand.objects.get(pk=action)
        repeated = submit(
            owner, item.case.credential, "action", proposal=proposal, action=action, cut=original.control_cut_digest
        )
        assert repeated == outcome
        assert ParticipantPowerReservation.objects.count() == 1
        later_proposal, later_action = uuid4(), uuid4()
        assert (
            submit(
                owner,
                item.case.credential,
                "proposal",
                proposal=later_proposal,
                action=later_action,
            ).state
            == "succeeded"
        )
        expected = owner.cursor(item.case.credential)
        repeated = submit(
            owner,
            item.case.credential,
            "action",
            proposal=proposal,
            action=action,
            cut=original.control_cut_digest,
        )
        assert repeated == outcome
        assert owner.cursor(item.case.credential) == expected
    finally:
        owner.close()
    recovered = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    try:
        assert recovered.cursor(item.case.credential) == expected
        repeated = submit(
            recovered, item.case.credential, "action", proposal=proposal, action=action, cut=original.control_cut_digest
        )
        assert repeated == outcome
        assert ParticipantPowerReservation.objects.count() == 1
    finally:
        recovered.close()


def test_original_request_nonce_cannot_be_rebased_to_the_latest_cut(product_range, tmp_path):
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from engine.models import ParticipantPowerReservation

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    proposal, action = uuid4(), uuid4()
    try:
        result = submit(owner, item.case.credential, "proposal", proposal=proposal, action=action)
        assert result.state == "succeeded"
        with pytest.raises(ValueError, match="Native participant request unavailable"):
            submit(owner, item.case.credential, "proposal", proposal=proposal, action=action)
        assert owner.cursor(item.case.credential).history_head == 1
        assert not ParticipantPowerReservation.objects.exists()
    finally:
        owner.close()


def test_installed_owner_serializes_verified_invocation_with_control_mutations(
    product_range, tmp_path, settings, monkeypatch
):
    from pydantic import SecretStr

    from cms.services._participant_control_owner import open_native_participant_control_owner
    from engine.models import ParticipantPowerReservation
    from engine.services import authenticate_native_power_operation, finish_native_power_invocation
    from tests.engine.services.test_native_participant_invocation import install_workload

    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "synthetic-native-provisioner"
    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    proposal, action = uuid4(), uuid4()
    try:
        for kind in ("proposal", "approval", "action"):
            outcome = submit(owner, item.case.credential, kind, proposal=proposal, action=action)
            assert outcome.state == "succeeded"
        reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
        install_workload(item.case, None, reservation.launch_intent.operation_id, monkeypatch)
        token = SecretStr("fixture.bound.token")
        route = authenticate_native_power_operation(reservation.launch_intent.operation_id, token)
        grant = owner.begin_invocation(route, member_ref="provision.node.web#0", token=token, attempt_id=uuid4())
        assert grant.operation_id == route.operation_id
        from cms.models import ParticipantControlCommand

        original = ParticipantControlCommand.objects.get(pk=action)
        assert (
            submit(
                owner,
                item.case.credential,
                "action",
                proposal=proposal,
                action=action,
                cut=original.control_cut_digest,
            )
            == outcome
        )
        with pytest.raises(ValueError, match="Native invocation remains unresolved"):
            submit(owner, item.case.credential, "proposal", proposal=uuid4(), action=uuid4())
        with pytest.raises(ValueError, match="Native invocation remains unresolved"):
            owner.close()
        finish_native_power_invocation(invocation_id=grant.invocation_id, attempt_id=grant.attempt_id, token=token)
    finally:
        owner.close()


def test_failed_sdk_admission_retracts_committed_held_work_and_exact_retry_stays_failed(
    product_range, tmp_path, monkeypatch
):
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from cms.services._participant_control_runtime_port import NativeParticipantRuntimePort
    from engine.models import ParticipantPowerReservation

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    original = NativeParticipantRuntimePort.reserve

    def after_reservation(self, action):
        original(self, action)
        raise ValueError("Synthetic callback failed after held commit")

    monkeypatch.setattr(NativeParticipantRuntimePort, "reserve", after_reservation)
    proposal, action = uuid4(), uuid4()
    try:
        for kind in ("proposal", "approval"):
            assert submit(owner, item.case.credential, kind, proposal=proposal, action=action).state == "succeeded"
        outcome = submit(owner, item.case.credential, "action", proposal=proposal, action=action)
        assert outcome.state == "failed"
        held = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
        assert held.fenced_at is not None
        assert held.released_at is None
        assert held.launch_intent.status == "HELD"
        item.case.row.refresh_from_db()
        assert item.case.row.status == "ready"
        assert item.case.row.provisioner_operation_id is None
        command = ParticipantControlCommand.objects.get(pk=action)
        assert command.dispatch_fenced_at is not None
        assert (
            submit(
                owner, item.case.credential, "action", proposal=proposal, action=action, cut=command.control_cut_digest
            )
            == outcome
        )
        assert ParticipantPowerReservation.objects.count() == 1
    finally:
        owner.close()


@pytest.mark.parametrize("failed", [False, True])
def test_restart_recovers_sdk_receipt_after_loss_before_native_correlation(
    product_range, tmp_path, monkeypatch, failed
):
    import cms.services._participant_control_owner as implementation
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from cms.services._participant_control_runtime_port import NativeParticipantRuntimePort
    from engine.models import ParticipantPowerReservation

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    proposal, action = uuid4(), uuid4()
    for kind in ("proposal", "approval"):
        assert submit(owner, item.case.credential, kind, proposal=proposal, action=action).state == "succeeded"
    original = implementation.correlate_native_control_operation
    reserve = NativeParticipantRuntimePort.reserve
    if failed:

        def fail_after_reservation(self, native_action):
            reserve(self, native_action)
            raise ValueError("Synthetic callback failed after held commit")

        monkeypatch.setattr(NativeParticipantRuntimePort, "reserve", fail_after_reservation)

    def lost(binding_id, command_id, operation_id):
        raise RuntimeError("Synthetic receipt response lost before SQL correlation")

    monkeypatch.setattr(implementation, "correlate_native_control_operation", lost)
    with pytest.raises(RuntimeError, match="response lost"):
        submit(owner, item.case.credential, "action", proposal=proposal, action=action)
    command = ParticipantControlCommand.objects.get(pk=action)
    held = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
    assert command.portable_operation_uuid is None
    assert held.released_at is None and held.launch_intent.status == "HELD"
    monkeypatch.setattr(implementation, "correlate_native_control_operation", original)
    if failed:
        monkeypatch.setattr(NativeParticipantRuntimePort, "reserve", reserve)
        assert submit(owner, item.case.credential, "proposal", proposal=uuid4(), action=uuid4()).state == "succeeded"
    expected = owner.cursor(item.case.credential)
    owner.close()
    monkeypatch.setattr(implementation, "correlate_native_control_operation", original)
    recovered = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    try:
        outcome = submit(
            recovered, item.case.credential, "action", proposal=proposal, action=action, cut=command.control_cut_digest
        )
        assert outcome.state == ("failed" if failed else "succeeded")
        assert recovered.cursor(item.case.credential) == expected
        held.refresh_from_db()
        assert (held.released_at is None) is failed
        assert ParticipantPowerReservation.objects.count() == 1
        assert ParticipantControlCommand.objects.get(pk=action).portable_operation_uuid == outcome.operation_id
    finally:
        recovered.close()


def test_cancelled_review_cannot_regain_permission_through_later_approval_or_original_retry(product_range, tmp_path):
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_owner import open_native_participant_control_owner
    from engine.models import ParticipantPowerReservation

    item = product_range
    binding = bind(item)
    owner = open_native_participant_control_owner(item.case.credential, binding.id, store_root=tmp_path)
    proposal, action, approval, cancellation = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        for kind, request in (("proposal", proposal), ("approval", approval)):
            assert (
                submit(owner, item.case.credential, kind, proposal=proposal, action=action, request_id=request).state
                == "succeeded"
            )
        original = NativeControlSubmission(
            request_id=cancellation,
            kind="cancellation",
            verb="pause",
            proposal_id=proposal,
            action_id=action,
            expected_cut_digest=owner.cursor(item.case.credential).control_cut_digest,
            decision_id=approval,
        )
        assert owner.submit(item.case.credential, original).state == "succeeded"
        assert submit(owner, item.case.credential, "approval", proposal=proposal, action=action).state == "failed"
        assert submit(owner, item.case.credential, "action", proposal=proposal, action=action).state == "failed"
        assert not ParticipantPowerReservation.objects.exists()
        assert owner.submit(item.case.credential, original).state == "succeeded"
        assert not ParticipantPowerReservation.objects.exists()
        assert ParticipantControlCommand.objects.get(pk=action).dispatch_fenced_at is not None
    finally:
        owner.close()
