"""Portable admission must commit before an audited native reservation can launch."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from shared.native_participant import NativeParticipantPowerAction, NativeRuntimeCoordinates
from tests.engine.services.test_native_compiler_context import compiled_native, tenant

__all__ = ["compiled_native", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("fault", ["proof", "generation", "custody"])
def test_prepared_reservation_rechecks_local_authority_after_product_locks(native_action, fault):
    from engine.models import ParticipantPowerReservation
    from engine.services import commit_native_participant_power, prepare_native_participant_power

    case, action = native_action
    prepared = prepare_native_participant_power(case.credential, case.request_id, action)
    if fault == "proof":
        case.actor.is_active = False
        case.actor.save(update_fields=["is_active"])
    elif fault == "generation":
        case.row.resource_generation = uuid4()
        case.row.save(update_fields=["resource_generation"])
    else:
        case.row.owner_principal_uuid = uuid4()
        case.row.save(update_fields=["owner_principal_uuid"])
    with pytest.raises(ValueError):
        commit_native_participant_power(prepared)
    assert not ParticipantPowerReservation.objects.exists()


def test_native_work_requires_an_exact_original_approval_reference(native_action):
    from engine.models import ParticipantPowerReservation

    case, action = native_action
    with pytest.raises(ValueError):
        _reserve(case, replace(action, approval_ref=""))
    assert not ParticipantPowerReservation.objects.exists()


@pytest.fixture(params=["pause", "resume"])
def native_action(compiled_native, request):
    return _native_action_case(compiled_native, request.param)


def _native_action_case(case, verb):
    from engine.models import RaesCompilerInputBinding

    row = case.row
    row.range_backend = "gce"
    row.status = "ready" if verb == "pause" else "paused"
    row.provisioned_instances = [
        {
            "uuid": "provision.node.web#0",
            "instance_id": "synthetic-web",
            "status": row.status,
            "native_power_target": {
                "backend": "gce",
                "project_id": "synthetic-project",
                "zone": "europe-west3-a",
                "instance_name": "synthetic-web",
                "bootstrap_capability": "standard",
            },
            "native_power_incarnation": {
                "instance_identity": "123",
                "disks": [{"name": "synthetic-boot", "identity": "456"}],
            },
        }
    ]
    row.save(update_fields=["range_backend", "status", "provisioned_instances"])
    binding = RaesCompilerInputBinding.objects.get(range=row)
    # The fixture's compiler owns the resolved participant references. A product
    # controller mapping remains an independent admission made by its owner.
    action = NativeParticipantPowerAction(
        coordinates=NativeRuntimeCoordinates(binding.binding_ref, row.resource_generation, uuid4()),
        participant_address="participant.behavior.analyst",
        controller_address="participant.behavior.analyst",
        episode_id="episode:synthetic",
        action_id=str(uuid4()),
        proposal_ref=str(uuid4()),
        action_contract_address=f"participant.action-contract.request-{verb}",
        observation_boundary_address="participant.observation-boundary.native-status",
        target_addresses=("provision.node.web",),
        verb=verb,
        implementation_selection_digest="sha256:" + "a" * 64,
        compiler_input_digest=case.context.compiler_input_digest,
        control_cut_digest="sha256:" + "c" * 64,
        approval_ref=str(uuid4()),
    )
    return case, action


def _reserve(case, action):
    from engine.services._native_participant_power import reserve_native_participant_power

    return reserve_native_participant_power(case.credential, case.request_id, action)


def test_reservation_has_immutable_input_strict_audit_and_cannot_be_claimed_for_dispatch(native_action):
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from engine.models import OperationInput, ParticipantPowerReservation, ProvisionerLaunchIntent

    case, action = native_action
    operation_id = _reserve(case, action)
    assert isinstance(operation_id, UUID)
    intent = ProvisionerLaunchIntent.objects.get(operation_id=operation_id)
    assert intent.status == "HELD"
    assert OperationInput.objects.filter(operation_id=operation_id).exists()
    reservation = ParticipantPowerReservation.objects.get(launch_intent=intent)
    assert reservation.action_id == UUID(action.action_id)
    assert reservation.run_id == action.coordinates.run_id
    assert reservation.portable_operation_uuid is None
    assert reservation.control_cut_digest == action.control_cut_digest
    assert Command._claim_next(intent_id=intent.intent_id) is None
    assert _reserve(case, action) == operation_id


def test_failed_strict_audit_rolls_back_the_entire_reservation(native_action, monkeypatch):
    from engine.models import ParticipantPowerReservation, ProvisionerLaunchIntent
    from engine.services import _native_participant_power

    case, action = native_action
    previous = case.row.status

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic audit unavailable")

    monkeypatch.setattr(_native_participant_power, "audit_log", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _reserve(case, action)
    case.row.refresh_from_db()
    assert case.row.status == previous
    assert not ParticipantPowerReservation.objects.exists()
    assert not ProvisionerLaunchIntent.objects.filter(payload__operation=action.verb).exists()


@pytest.mark.parametrize("fault", ["generation", "binding", "compiler-input", "footprint", "principal"])
def test_stale_or_unauthorized_native_action_never_reserves_work(native_action, fault):
    from engine.models import ParticipantPowerReservation

    case, action = native_action
    if fault == "generation":
        action = replace(action, coordinates=replace(action.coordinates, resource_generation=uuid4()))
    elif fault == "binding":
        action = replace(action, coordinates=replace(action.coordinates, binding_ref=uuid4()))
    elif fault == "compiler-input":
        action = replace(action, compiler_input_digest="sha256:" + "0" * 64)
    elif fault == "footprint":
        action = replace(action, target_addresses=("provision.node.foreign",))
    else:
        case.actor.policy_principals.clear()
    with pytest.raises((PermissionError, ValueError)):
        _reserve(case, action)
    assert not ParticipantPowerReservation.objects.exists()


def test_an_action_identity_cannot_reserve_a_second_meaning(native_action):
    case, action = native_action
    _reserve(case, action)
    with pytest.raises(ValueError, match="Native participant operation unavailable"):
        _reserve(case, replace(action, episode_id="episode:foreign"))


def test_a_held_reservation_cannot_launch_through_the_local_dispatch_shortcut(
    native_action,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from engine.ecs import _local

    case, action = native_action
    monkeypatch.setattr(_local, "_is_local_provisioner_enabled", lambda: True)

    def prohibited(*args, **kwargs):
        raise AssertionError("Held participant work must not dispatch")

    monkeypatch.setattr(_local, "drain_local_intent", prohibited)
    with django_capture_on_commit_callbacks(execute=True):
        _reserve(case, action)


def test_a_shared_ngfw_cannot_enter_the_selected_participant_power_footprint(native_action):
    from engine.models import Instance, ParticipantPowerReservation

    case, action = native_action
    gateway = Instance.objects.create(request=case.row.request, role="ngfw")
    case.row.ngfw_instance = gateway
    case.row.save(update_fields=["ngfw_instance"])
    with pytest.raises(ValueError, match="Native participant operation unavailable"):
        _reserve(case, action)
    assert not ParticipantPowerReservation.objects.exists()


def test_a_committed_portable_admission_is_correlated_without_releasing_native_work(native_action):
    from engine.models import ParticipantPowerReservation, ProvisionerLaunchIntent
    from engine.services._native_participant_power import record_native_participant_admission

    case, action = native_action
    operation_id = _reserve(case, action)
    portable_id = uuid4()
    record_native_participant_admission(
        case.credential,
        UUID(action.action_id),
        portable_operation_uuid=portable_id,
        control_cut_digest=action.control_cut_digest,
    )
    reservation = ParticipantPowerReservation.objects.get(action_id=action.action_id)
    assert reservation.portable_operation_uuid == portable_id
    assert ProvisionerLaunchIntent.objects.get(operation_id=operation_id).status == "HELD"


@pytest.mark.parametrize("fault", ["cut", "credential", "generation"])
def test_changed_admission_facts_cannot_commit_a_native_receipt(native_action, fault):
    from engine.models import ParticipantPowerReservation
    from engine.services._native_participant_power import record_native_participant_admission

    case, action = native_action
    _reserve(case, action)
    digest = action.control_cut_digest
    if fault == "cut":
        digest = "sha256:" + "d" * 64
    elif fault == "credential":
        case.actor.policy_principals.clear()
    else:
        case.row.resource_generation = uuid4()
        case.row.save(update_fields=["resource_generation"])
    with pytest.raises((ValueError, PermissionError)):
        record_native_participant_admission(
            case.credential,
            UUID(action.action_id),
            portable_operation_uuid=uuid4(),
            control_cut_digest=digest,
        )
    assert ParticipantPowerReservation.objects.get(action_id=action.action_id).portable_operation_uuid is None


def test_receipt_correlation_is_immutable_and_idempotent(native_action):
    from engine.models import ParticipantPowerReservation
    from engine.services._native_participant_power import record_native_participant_admission

    case, action = native_action
    _reserve(case, action)
    portable_id = uuid4()
    for _ in range(2):
        record_native_participant_admission(
            case.credential,
            UUID(action.action_id),
            portable_operation_uuid=portable_id,
            control_cut_digest=action.control_cut_digest,
        )
    with pytest.raises(ValueError, match="Native participant operation unavailable"):
        record_native_participant_admission(
            case.credential,
            UUID(action.action_id),
            portable_operation_uuid=uuid4(),
            control_cut_digest=action.control_cut_digest,
        )
    assert ParticipantPowerReservation.objects.get(action_id=action.action_id).portable_operation_uuid == portable_id


def test_failed_receipt_audit_keeps_the_operation_held_and_uncorrelated(native_action, monkeypatch):
    from engine.models import ParticipantPowerReservation
    from engine.services import _native_participant_power

    case, action = native_action
    _reserve(case, action)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic receipt audit unavailable")

    monkeypatch.setattr(_native_participant_power, "audit_log", unavailable)
    with pytest.raises(RuntimeError, match="receipt audit unavailable"):
        _native_participant_power.record_native_participant_admission(
            case.credential,
            UUID(action.action_id),
            portable_operation_uuid=uuid4(),
            control_cut_digest=action.control_cut_digest,
        )
    reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action.action_id)
    assert reservation.portable_operation_uuid is None
    assert reservation.launch_intent.status == "HELD"


def test_receipt_correlation_does_not_decrypt_private_compiler_parameters(native_action, settings):
    from cryptography.fernet import Fernet

    from engine.services._native_participant_power import record_native_participant_admission

    case, action = native_action
    _reserve(case, action)
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    record_native_participant_admission(
        case.credential,
        UUID(action.action_id),
        portable_operation_uuid=uuid4(),
        control_cut_digest=action.control_cut_digest,
    )
