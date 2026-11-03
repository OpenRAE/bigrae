"""Accepted values are confidential, immutable and fenced by the operation epoch."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.db import IntegrityError, transaction
from shifter_adapter_sdk.runtime import RuntimeInput, RuntimePlan

from engine.launch_intents import enqueue_provisioner_launch
from engine.models import Range, RuntimePluginInstallation, RuntimePluginInvocation, RuntimePluginRangeBinding
from engine.operation_inputs import operation_input_payload
from engine.services import RangeBindings, bind_runtime_plugin, create_raes_range, install_runtime_plugin
from engine.services import _runtime_plugin_operations as operations
from engine.services._runtime_plugin_preparation import preparation_result_secret
from shared.field_encryption import decrypt_value
from shared.raes.operation_input import parse_raes_operation_input
from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.engine.services.test_runtime_plugin_bindings import pack as pack
from tests.shared.raes.test_runtime_preparation import preparation as preparation

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def pending(pack, preparation, settings, monkeypatch):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    pin, plan, _ = preparation
    plan["resources"]["node.example"]["payload"]["spec"] = {}
    plan["operations"][0]["payload"]["spec"] = {}
    installed = install_runtime_plugin(pack.credential, pack.organization.uuid, pin.manifest.model_dump(mode="json"))
    RuntimePluginInstallation.objects.filter(pk=installed.id).update(state="ready")
    bind_runtime_plugin(pack.credential, pack.scope, installed.id, {"targets": {}})
    request_id = uuid4()
    create_raes_range(
        request_id=request_id,
        user_id=pack.actor.id,
        workspace_id=1,
        compiled_plan=plan,
        backend_admission=BackendAdmission(True, "gce", InstantiationPurpose.LIVE_FIRE, "", ""),
        bindings=RangeBindings(runtime_plugin_scope=pack.scope),
    )
    enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request_id)])
    target = Range.objects.get(request__request_id=request_id)
    row = RuntimePluginInvocation.objects.get(request_id=request_id)
    request = RuntimeInput.model_validate(row.input)
    result = RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase="prepare",
        status="planned",
        provisioning_values=[
            {
                "address": "node.example",
                "concern": "synthetic-values",
                "payload_pointer": "/settings/selected",
                "value": "PRIVATE_PREPARATION_VALUE",
            }
        ],
    )
    dispatch = Mock()
    monkeypatch.setattr(operations, "launch_plugin", dispatch)
    monkeypatch.setattr(operations, "_file_secret", lambda *_: None)
    monkeypatch.setattr(operations, "_pull_secret", lambda *_: None)
    monkeypatch.setattr(operations, "observe_plugin", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(operations, "interrupt_plugin", lambda *_: None)
    return SimpleNamespace(target=target, row=row, request=request, result=result, dispatch=dispatch)


def test_accepted_preparation_is_encrypted_and_snapshotted_for_destroy(pending, settings):
    operations._reconcile(pending.row)
    pending.row.refresh_from_db()
    binding = RuntimePluginRangeBinding.objects.get(range=pending.target)
    assert pending.row.state == "planned"
    assert binding.preparation == pending.row.result
    assert "PRIVATE_PREPARATION_VALUE" not in str(binding.preparation)
    assert "PRIVATE_PREPARATION_VALUE" in decrypt_value(binding.preparation["encrypted_result"])
    secret = pending.dispatch.call_args.kwargs["result_secret"]
    assert secret == preparation_result_secret(pending.request)
    assert secret != settings.FIELD_ENCRYPTION_KEY
    snapshot = parse_raes_operation_input(
        operation_input_payload(
            pending.target,
            "raes-range",
            pending.target.request,
            operation="destroy",
        )
    )
    assert snapshot.runtime_preparation.model_dump(mode="json") == binding.preparation


@pytest.mark.parametrize("field", ["preparation", "pin", "pin_digest", "installation_id", "range_id"])
def test_sql_cannot_replace_retained_preparation_or_its_parent_identity(pending, field):
    operations._reconcile(pending.row)
    row = RuntimePluginRangeBinding.objects.get(range=pending.target)
    replacement = None if field == "preparation" else ({} if field == "pin" else "changed")
    if field.endswith("_id"):
        replacement = uuid4() if field == "installation_id" else pending.target.id + 1
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimePluginRangeBinding.objects.filter(pk=row.pk).update(**{field: replacement})


def test_exact_value_is_rejected_before_any_accepted_preparation(pending, monkeypatch, caplog):
    raw = pending.result.model_dump(mode="json")
    raw["provisioning_values"][0]["payload_pointer"] = "/settings/fixed"
    invalid = RuntimePlan.model_validate(raw)
    monkeypatch.setattr(operations, "observe_plugin", lambda *_args, **_kwargs: invalid)
    operations._reconcile(pending.row)
    pending.row.refresh_from_db()
    assert pending.row.state == "failed" and pending.row.result is None
    assert RuntimePluginRangeBinding.objects.get(range=pending.target).preparation is None
    assert "PRIVATE_PREPARATION_VALUE" not in caplog.text


def test_destroy_epoch_fences_late_acceptance_and_records_pre_effect_absence(pending, monkeypatch):
    def late_result(*_args, **_kwargs):
        Range.objects.filter(pk=pending.target.pk).update(provisioner_operation_id=uuid4(), status="destroying")
        return pending.result

    monkeypatch.setattr(operations, "observe_plugin", late_result)
    operations._reconcile(pending.row)
    pending.row.refresh_from_db()
    assert pending.row.state == "failed" and pending.row.result is None
    assert RuntimePluginRangeBinding.objects.get(range=pending.target).preparation is None
    pending.target.refresh_from_db()
    payload = operation_input_payload(pending.target, "raes-range", pending.target.request, operation="destroy")
    assert parse_raes_operation_input(payload).runtime_preparation.state == "unprepared"


def test_retry_queue_reuses_accepted_source_without_running_preparation_again(pending):
    from engine.models import OperationInput

    operations._reconcile(pending.row)
    pending.row.refresh_from_db()
    original = pending.row.result
    envelope = OperationInput.objects.get(operation_id=pending.row.operation_id).envelope.copy()
    retry = uuid4()
    envelope["operation_id"] = str(retry)
    operations.queue_runtime_plugin_plans(envelope)
    queued = RuntimePluginInvocation.objects.get(operation_id=retry, phase="prepare")
    assert queued.state == "planned" and queued.result == original
    assert queued.result["source_operation_id"] == str(pending.row.operation_id)
    assert queued.input_digest != pending.row.input_digest
    assert pending.dispatch.call_count == 1


@pytest.mark.parametrize("when", ["before-dispatch", "during-observation"])
def test_cancel_intent_fences_preparation_even_before_the_range_changes_state(pending, monkeypatch, when):
    from engine.models import InterruptState, ProvisionerLaunchIntent

    def cancel():
        ProvisionerLaunchIntent.objects.filter(operation_id=pending.row.operation_id).update(
            interrupt_state=InterruptState.REQUESTED,
        )

    if when == "before-dispatch":
        cancel()
    else:

        def observed(*_args, **_kwargs):
            cancel()
            return pending.result

        monkeypatch.setattr(operations, "observe_plugin", observed)
    operations._reconcile(pending.row)
    pending.row.refresh_from_db()
    assert pending.row.state == "failed" and pending.row.result is None
    assert RuntimePluginRangeBinding.objects.get(range=pending.target).preparation is None
    if when == "before-dispatch":
        pending.dispatch.assert_not_called()
