"""The first-party file API, binding and launch pin share real CMS/Engine custody."""

import pytest

from cms.models import FileAssetUse, RangeInstance
from cms.services import create_raes_native_range, delete_file_asset
from engine.models import OperationInput, Range, RuntimePluginInstallation, RuntimePluginInvocation
from engine.services import install_runtime_plugin
from engine.services._runtime_plugin_bindings import retained_runtime_plugin_pin
from shared.authorization import TargetRef
from shared.credentials import resolve_credential_scope
from tests.cms.services.test_file_assets import _upload
from tests.cms.services.test_principal_uploads import storage_client
from tests.cms.test_runtime_plugin_packs import pack_api
from tests.cms.test_runtime_plugins import manifest, tenant
from tests.engine.services.test_runtime_plugin_pull_secret import pull_secret_env

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.postgres]
__all__ = ["manifest", "pack_api", "pull_secret_env", "storage_client", "tenant"]


@pytest.fixture
def file_launch(pack_api, tenant, manifest, storage_client, settings):
    from types import SimpleNamespace

    actor, organization = tenant
    from workspaces.services import add_account_member

    add_account_member(organization.account.uuid, actor.credential.principal)
    settings.ENGINE_TASK_CLUSTER = "synthetic-namespace"
    settings.ENGINE_TASK_DEFINITION = "example.test/synthetic@sha256:" + "1" * 64
    client, base, _, source, _ = pack_api
    scope = resolve_credential_scope(TargetRef("organization", organization.uuid))
    fixture = SimpleNamespace(credential=actor.credential, scope=scope)
    asset = _upload(fixture, storage_client, material=b"synthetic parameters")
    installed = install_runtime_plugin(
        actor.credential,
        organization.uuid,
        {
            **manifest,
            "version": "2",
            "required_files": ["parameters"],
        },
    )
    RuntimePluginInstallation.objects.filter(pk=installed.id).update(state="ready")
    target = client.get(base + "example/").json()["targets"][0]["address"]
    response = client.post(
        base + "example/",
        {
            "installation_id": str(installed.id),
            "pack_digest": source.package_digest,
            "bindings": {"targets": {"server": target}, "file_assets": {"parameters": str(asset.asset_uuid)}},
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    return fixture, source, asset


@pytest.mark.django_db(transaction=True)
def test_real_launch_pins_cms_file_use_and_byte_free_engine_operation(file_launch, pull_secret_env, monkeypatch):
    import base64
    from unittest.mock import Mock

    from django.db import connection

    from engine.services import _runtime_plugin_operations as controller
    from engine.services import reconcile_runtime_plugin_operations
    from shared.authorization import configured_authorization_provider, port

    provider = configured_authorization_provider()
    original = provider.check
    checked = []

    def check(request):
        assert not connection.in_atomic_block
        checked.append(request.action)
        return original(request)

    provider.check = check
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    actor, source, asset = file_launch
    result = create_raes_native_range(actor.credential, source.scenario_id, scope=actor.scope)
    instance = RangeInstance.objects.get(request__request_id=result.request_id)
    runtime = Range.objects.get(request__request_id=result.request_id)
    use = FileAssetUse.objects.get(range_instance=instance, input_name="parameters")
    pin = retained_runtime_plugin_pin(runtime)
    assert use.file_asset_id == pin.files["parameters"].version_id == asset.pk
    assert use.credential_uuid == actor.credential.credential_uuid
    assert RuntimePluginInvocation.objects.filter(request_id=result.request_id).count() == 3
    operation = OperationInput.objects.get(request_id=result.request_id)
    assert asset.s3_key not in str(operation.envelope)
    assert "synthetic parameters" not in str(operation.envelope)
    launched = Mock()
    monkeypatch.setattr(controller, "launch_plugin", launched)
    monkeypatch.setattr(controller, "observe_plugin", lambda *_args: None)
    assert reconcile_runtime_plugin_operations() == 3
    assert launched.call_count == 3
    secrets = pull_secret_env.core.create_namespaced_secret.call_args_list
    assert len(secrets) == 3
    for call in secrets:
        secret = call.kwargs["body"]
        assert secret["immutable"]
        assert secret["data"] == {"parameters": base64.b64encode(b"synthetic parameters").decode("ascii")}
        owner = secret["metadata"]["ownerReferences"][0]
        assert owner["uid"] == "job-uid"
        assert secret["metadata"]["name"] == owner["name"] + "-inputs"
    assert "organization.read_content" in checked


def test_deleted_required_file_refuses_real_launch_before_native_dispatch(file_launch):
    from cms.exceptions import CMSError
    from engine.models import ProvisionerLaunchIntent

    actor, source, asset = file_launch
    delete_file_asset(actor.credential, asset.pk)
    with pytest.raises(CMSError):
        create_raes_native_range(actor.credential, source.scenario_id, scope=actor.scope)
    assert not Range.objects.exists()
    assert not FileAssetUse.objects.exists()
    assert not OperationInput.objects.exists()
    assert not ProvisionerLaunchIntent.objects.exists()


def test_cancellation_during_file_read_prevents_worker_dispatch(file_launch, storage_client, monkeypatch):
    from unittest.mock import Mock

    from engine.services import _runtime_plugin_operations as controller

    actor, source, _ = file_launch
    result = create_raes_native_range(actor.credential, source.scenario_id, scope=actor.scope)
    launched = Mock()
    monkeypatch.setattr(controller, "launch_plugin", launched)
    monkeypatch.setattr(controller, "interrupt_plugin", Mock())

    def read(*_args, **_kwargs):
        Range.objects.filter(request__request_id=result.request_id).update(status="destroying")
        return b"synthetic parameters"

    storage_client.get_object.return_value["Body"].read.side_effect = read
    assert controller.reconcile_runtime_plugin_operations() == 3
    launched.assert_not_called()
    assert set(RuntimePluginInvocation.objects.values_list("state", flat=True)) == {"failed"}
