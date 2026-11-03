"""Native operation/preparation commits retain exclusive projects and recover original inputs."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.db import transaction
from django.utils import timezone
from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

from engine.models import (
    GcpRangeProjectUse,
    OperationInput,
    RuntimePluginInstallation,
    RuntimePluginRangeBinding,
)
from engine.operation_inputs import operation_input_payload
from engine.services._gcp_project_inputs import allocate_launch_projects, allocate_plan_projects, projects_for_input
from engine.services._runtime_plugin_cleanup import preparation_cleanup_payload
from engine.services._runtime_plugin_preparation import approved_preparation, retain_preparation
from shared.operation_envelope import MAX_RAES_INPUT_BYTES, OperationEnvelopeError, build_operation_envelope
from shared.raes.operation_input import RaesInputBindings, RaesRangeIdentity, build_raes_operation_input
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests
from tests.engine.services.test_gcp_range_projects import registration as registration
from tests.engine.services.test_gcp_range_projects import target_range
from tests.shared.raes.test_gcp_project_demands import native_plan as native_plan
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def source_input(target, plan, *, pin=None, leases=()):
    payload = build_raes_operation_input(
        plan=plan,
        bindings=RaesInputBindings(delivery=(), runtime_plugin=pin, gcp_projects=leases),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose=None,
        identity=RaesRangeIdentity(target.pk),
    )
    envelope = build_operation_envelope(
        operation_id=target.provisioner_operation_id,
        request_id=target.request.request_id,
        resource="raes-range",
        operation="provision",
        payload=payload,
    )
    return OperationInput.objects.create(
        operation_id=target.provisioner_operation_id,
        request_id=target.request.request_id,
        resource="raes-range",
        operation="provision",
        contract_version=envelope["contract_version"],
        envelope=envelope,
    )


def test_ordinary_launch_allocates_explicitly_and_cleanup_keeps_original_after_configuration_changes(
    registration, native_plan
):
    target = target_range(registration)
    _native, plan = native_plan
    target.range_config = plan
    target.save(update_fields=["range_config"])
    # A read projection cannot reserve a project, even inside a transaction.
    with pytest.raises(ValueError, match="unavailable"):
        projects_for_input(target, plan, None)
    assert not GcpRangeProjectUse.objects.filter(range=target).exists()
    payload = {"resource": "raes-range", "operation": "provision", "request_id": str(target.request.request_id)}
    with transaction.atomic():
        allocate_launch_projects(payload, target.provisioner_operation_id)
        leases = projects_for_input(target, plan, None)
        source = source_input(target, plan, leases=leases)
    assert len(leases) == 1 and leases[0].source_operation_id == target.provisioner_operation_id
    original = deepcopy(source.envelope["payload"])
    target.provisioner_operation_id, target.status, target.range_config = uuid4(), "destroying", {"changed": True}
    target.save(update_fields=["provisioner_operation_id", "status", "range_config"])
    assert operation_input_payload(target, "raes-range", target.request, operation="destroy") == original


def test_number_mismatch_rolls_back_project_uses_even_when_caller_catches_failure(registration, native_plan):
    target = target_range(registration)
    _native, plan = native_plan
    plan = deepcopy(plan)
    for resource in [
        plan["resources"]["provision.node.web"],
        *[op for op in plan["operations"] if op["address"] == "provision.node.web"],
    ]:
        resource["payload"]["spec"]["node"]["runtime"]["identity_authorities"][0]["resource_scopes"][0][
            "incarnation_id"
        ] = "111122223333"
    with transaction.atomic():
        with pytest.raises(ValueError, match="unavailable"):
            allocate_plan_projects(target, plan, canonical_digest(plan))
        assert not GcpRangeProjectUse.objects.filter(range=target).exists()


def test_held_project_blocks_owner_and_scope_moves_even_without_vpn(registration, native_plan):
    from engine.services._principal_range_scope import _assert_move_supported
    from engine.services._range_custody import (
        principal_range_owner_reassignment_available,
        range_owner_reassignment_available_by_request,
    )

    target = target_range(registration)
    allocate_plan_projects(target, native_plan[1], canonical_digest(native_plan[1]))
    target.status = "ready"
    target.save(update_fields=["status"])
    assert target.vpn_access_binding is None
    assert not principal_range_owner_reassignment_available(target)
    assert not range_owner_reassignment_available_by_request(target.request.request_id)
    with pytest.raises(ValueError, match="project custody"):
        _assert_move_supported(target, allow_event=True, allow_principal_vpn=True)


def test_late_preparation_cannot_reserve_under_another_operation(prepared_source):
    source = prepared_source
    record = approval(source)
    source_input(source.target, source.plan, pin=source.pin)
    source.target.provisioner_operation_id = uuid4()
    source.target.save(update_fields=["provisioner_operation_id"])
    with pytest.raises(ValueError, match="identity changed"):
        retain_preparation(source.target, record)
    assert not GcpRangeProjectUse.objects.filter(range=source.target).exists()


@pytest.fixture
def prepared_source(registration, native_plan, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    target = target_range(registration)
    _native, plan = native_plan
    pin = RuntimePluginPin(
        organization_uuid=registration.organization_uuid,
        installation_id=uuid4(),
        pack_id="synthetic",
        pack_digest="sha256:" + "a" * 64,
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.prepare",
            "version": "1",
            "distribution": "example-prepare",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "c" * 64,
            "capabilities": ["provision.prepare"],
            "required_bindings": [],
            "provisioning_concerns": ["runtime-identity-authorities"],
        },
        bindings={"targets": {}},
    )
    installed = RuntimePluginInstallation.objects.create(
        id=pin.installation_id,
        organization_uuid=pin.organization_uuid,
        plugin_id=pin.manifest.plugin_id,
        version=pin.manifest.version,
        manifest=pin.manifest.model_dump(mode="json"),
        manifest_digest=pin.manifest.digest,
        state="ready",
        probe_expires_at=timezone.now(),
    )
    binding = RuntimePluginRangeBinding.objects.create(
        range=target, installation=installed, pin=pin.model_dump(mode="json"), pin_digest=pin.digest
    )
    return SimpleNamespace(target=target, plan=plan, pin=pin, binding=binding)


def approval(source):
    target, pin, plan = source.target, source.pin, source.plan
    target.range_config = plan
    target.save(update_fields=["range_config"])
    (request,) = runtime_plugin_requests(pin, plan, target.provisioner_operation_id, target.pk, backend="gce")
    result = RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase="prepare",
        status="planned",
        provisioning_values=[],
    )
    record = approved_preparation(request, result, pin, plan)
    return record


def test_preparation_and_project_lease_commit_together_and_cleanup_carries_same_refs(prepared_source):
    source = prepared_source
    record = approval(source)
    stored = source_input(source.target, source.plan, pin=source.pin)
    with transaction.atomic():
        accepted = retain_preparation(source.target, record)
    assert len(accepted.cloud_projects) == 1
    assert accepted.cloud_projects[0].source_operation_id == record.source_operation_id
    source.binding.refresh_from_db()
    assert source.binding.preparation == accepted.model_dump(mode="json")
    cleanup = preparation_cleanup_payload(stored.envelope, accepted)
    assert cleanup["gcp_projects"] == cleanup["runtime_preparation"]["cloud_projects"]


def test_cleanup_budget_failure_after_reservation_rolls_back_custody(prepared_source):
    source = prepared_source
    record = approval(source)
    # Leave room for the original accepted mapping, but not the added lease
    # references. The full source and accepted mapping fit before reservation.
    initial = build_raes_operation_input(
        plan=source.plan,
        bindings=RaesInputBindings(delivery=(), runtime_plugin=source.pin, runtime_preparation=record),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose=None,
        identity=RaesRangeIdentity(source.target.pk),
    )
    envelope = build_operation_envelope(
        operation_id=record.source_operation_id,
        request_id=source.target.request.request_id,
        resource="raes-range",
        operation="destroy",
        payload=initial,
    )
    size = len(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
    padding = (MAX_RAES_INPUT_BYTES - size - 128) // 2
    for resource in [
        source.plan["resources"]["provision.node.web"],
        *[op for op in source.plan["operations"] if op["address"] == "provision.node.web"],
    ]:
        resource["payload"]["spec"]["node"]["description"] = "x" * padding
    record = approval(source)
    stored = source_input(source.target, source.plan, pin=source.pin)
    preparation_cleanup_payload(stored.envelope, record)
    with transaction.atomic():
        with pytest.raises(OperationEnvelopeError, match="exceeds"):
            retain_preparation(source.target, record)
        assert not GcpRangeProjectUse.objects.filter(range=source.target).exists()
        source.binding.refresh_from_db()
        assert source.binding.preparation is None
