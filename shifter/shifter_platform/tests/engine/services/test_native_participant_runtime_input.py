"""A controller installation needs current compiler and native power bindings."""

from uuid import uuid4

import pytest

from tests.engine.services.test_native_participant_reservation import compiled_native, native_action, tenant

__all__ = ["compiled_native", "native_action", "tenant"]
pytestmark = pytest.mark.django_db


def read(case):
    from engine.services import read_range_participant_power_input

    return read_range_participant_power_input(case.credential, case.request_id)


def test_installation_input_joins_current_compiler_and_native_footprint(native_action):
    case, action = native_action
    loaded = read(case)
    assert loaded.compiler.context == case.context
    assert loaded.compiler.binding_ref == action.coordinates.binding_ref
    assert loaded.power.resource_generation == action.coordinates.resource_generation
    assert loaded.power.members[0].target.instance_name == "synthetic-web"
    assert "synthetic-web" not in repr(loaded)


@pytest.mark.parametrize("fault", ["backend", "incarnation", "state", "generation", "authority", "firewall"])
def test_unqualified_or_foreign_installation_input_is_withheld(native_action, fault):
    from engine.services import EngineError

    case, _ = native_action
    if fault == "backend":
        case.row.range_backend = "aws"
    elif fault == "incarnation":
        case.row.provisioned_instances[0].pop("native_power_incarnation")
    elif fault == "state":
        case.row.status = "destroying"
    elif fault == "generation":
        case.row.resource_generation = uuid4()
    elif fault == "authority":
        case.actor.policy_principals.clear()
    else:
        from engine.models import Instance

        case.row.ngfw_instance = Instance.objects.create(request=case.row.request, role="ngfw")
    case.row.save(
        update_fields=["range_backend", "provisioned_instances", "status", "resource_generation", "ngfw_instance"]
    )
    with pytest.raises((EngineError, PermissionError)):
        read(case)


def test_unqualified_native_input_is_refused_before_private_decryption(native_action, settings):
    from cryptography.fernet import Fernet

    from engine.services import EngineError

    case, _ = native_action
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    case.row.provisioned_instances[0].pop("native_power_incarnation")
    case.row.save(update_fields=["provisioned_instances"])
    with pytest.raises(EngineError, match="Native participant installation input unavailable"):
        read(case)


@pytest.mark.parametrize("fault", ["generation", "custody", "footprint", "proof"])
def test_prepared_installation_must_fence_current_native_facts(native_action, fault):
    from django.db import transaction

    from engine.services import (
        EngineError,
        fence_range_participant_power_input,
        prepare_range_participant_power_input,
    )

    case, _ = native_action
    prepared = prepare_range_participant_power_input(case.credential, case.request_id)
    if fault == "generation":
        case.row.resource_generation = uuid4()
    elif fault == "custody":
        case.row.owner_principal_uuid = uuid4()
    elif fault == "footprint":
        case.row.provisioned_instances = []
    else:
        case.actor.is_active = False
        case.actor.save(update_fields=["is_active"])
    case.row.save(update_fields=["resource_generation", "owner_principal_uuid", "provisioned_instances"])
    with pytest.raises(EngineError), transaction.atomic():
        fence_range_participant_power_input(prepared)


def test_prepared_installation_requires_atomic_caller_and_returns_same_private_input(native_action):
    from django.db import transaction

    from engine.services import (
        fence_range_participant_power_input,
        prepare_range_participant_power_input,
    )

    case, _ = native_action
    prepared = prepare_range_participant_power_input(case.credential, case.request_id)
    with transaction.atomic():
        assert fence_range_participant_power_input(prepared) == prepared.input


@pytest.mark.parametrize("status", ["pausing", "resuming", "failed"])
def test_bound_owner_recovery_reads_its_original_input_without_requalifying_new_work(native_action, status):
    from engine.services import prepare_bound_range_participant_power_input

    case, action = native_action
    case.row.status = status
    case.row.save(update_fields=["status"])
    prepared = prepare_bound_range_participant_power_input(case.credential, case.request_id, action.coordinates)
    assert prepared.input.compiler.binding_ref == action.coordinates.binding_ref
    assert prepared.input.compiler.context == case.context
    assert case.row.status == status


def test_foreign_run_coordinates_are_refused_before_private_decryption(native_action, settings):
    from dataclasses import replace

    from cryptography.fernet import Fernet

    from engine.services import EngineError, prepare_bound_range_participant_power_input

    case, action = native_action
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(EngineError, match="Native participant installation input unavailable"):
        prepare_bound_range_participant_power_input(
            case.credential, case.request_id, replace(action.coordinates, binding_ref=uuid4())
        )


@pytest.mark.parametrize("fault", ["absent", "ambiguous", "foreign-generation"])
def test_power_binding_requires_one_exact_original_provisioning_input(native_action, fault):
    from copy import deepcopy

    from engine.models import OperationInput
    from engine.services import EngineError

    case, _ = native_action
    original = OperationInput.objects.get(request_id=case.request_id, resource="raes-range", operation="provision")
    if fault == "absent":
        original.delete()
    else:
        envelope = deepcopy(original.envelope)
        envelope["operation_id"] = str(uuid4())
        if fault == "foreign-generation":
            original.delete()
            envelope["payload"]["resource_generation"] = str(uuid4())
        OperationInput.objects.create(
            operation_id=envelope["operation_id"],
            request_id=case.request_id,
            resource="raes-range",
            operation="provision",
            contract_version=envelope["contract_version"],
            envelope=envelope,
        )
    with pytest.raises(EngineError, match="provisioning origin unavailable"):
        read(case)
