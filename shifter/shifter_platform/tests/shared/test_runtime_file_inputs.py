"""The configured CMS material boundary supplies only exact, bounded versions."""

import hashlib
from uuid import uuid4

import pytest

from shared import runtime_file_inputs as files


@pytest.fixture
def binding():
    return files.RuntimeFileBinding(
        asset_uuid=uuid4(), version_id=1, sha256="sha256:" + hashlib.sha256(b"data").hexdigest(), size_bytes=4
    )


@pytest.fixture(autouse=True)
def unbound(monkeypatch):
    monkeypatch.setattr(files, "_provider", None)


def test_file_material_provider_is_required_only_for_declared_files(binding):
    assert files.load_file_input_material(uuid4(), {}) == {}
    with pytest.raises(ValueError):
        files.load_file_input_material(uuid4(), {"parameters": binding})


def test_provider_gets_exact_versions_and_cannot_rebind_the_port(binding):
    request_id = uuid4()
    seen = []

    def provider(identifier, bindings):
        seen.append((identifier, bindings))
        return {"parameters": b"data"}

    files.bind_file_input_provider(provider)
    files.bind_file_input_provider(provider)
    assert files.load_file_input_material(request_id, {"parameters": binding}) == {"parameters": b"data"}
    assert seen == [(request_id, {"parameters": binding})]
    with pytest.raises(ValueError):
        files.bind_file_input_provider(lambda *_args: {})


@pytest.mark.parametrize("material", [{}, {"other": b"data"}, {"parameters": b"fake"}, {"parameters": b"data!"}])
def test_provider_cannot_omit_replace_or_change_admitted_material(binding, material):
    files.bind_file_input_provider(lambda *_args: material)
    with pytest.raises(ValueError):
        files.load_file_input_material(uuid4(), {"parameters": binding})


def test_provider_failures_do_not_expose_private_diagnostics(binding):
    def provider(*_args):
        raise RuntimeError("PRIVATE_FILE_DIAGNOSTIC")

    files.bind_file_input_provider(provider)
    with pytest.raises(ValueError) as error:
        files.load_file_input_material(uuid4(), {"parameters": binding})
    assert "PRIVATE_FILE_DIAGNOSTIC" not in str(error.value)
    assert error.value.__suppress_context__


def test_file_pin_projects_only_digest_and_size_to_the_worker(binding):
    from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests

    pin = RuntimePluginPin(
        organization_uuid=uuid4(),
        pack_id="synthetic",
        pack_digest="sha256:" + "b" * 64,
        installation_id=uuid4(),
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.adapter",
            "version": "1",
            "distribution": "example-adapter",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "a" * 64,
            "capabilities": ["guest.configure", "guest.verify"],
            "required_bindings": ["server"],
            "required_files": ["parameters"],
        },
        bindings={"targets": {"server": "node.web"}, "file_assets": {"parameters": binding.asset_uuid}},
        files={"parameters": binding},
    )
    plan = {"resources": {"node.web": {"resource_type": "node", "payload": {"os_family": "linux"}}}}
    requests = runtime_plugin_requests(pin, plan, uuid4(), 1)
    assert {request.phase for request in requests} == {"validate", "configure", "verify"}
    for request in requests:
        assert request.files["parameters"].model_dump(mode="json") == {
            "sha256": binding.sha256,
            "size_bytes": binding.size_bytes,
        }
        assert str(binding.asset_uuid) not in request.model_dump_json()

    payload = pin.model_dump(mode="json")
    payload["files"]["parameters"]["asset_uuid"] = str(uuid4())
    with pytest.raises(ValueError):
        RuntimePluginPin.model_validate(payload)


def test_empty_file_fields_preserve_old_pin_and_binding_digests():
    from shifter_adapter_sdk.runtime import canonical_digest

    from shared.runtime_plugin_binding import RuntimePluginPin

    before = {
        "organization_uuid": str(uuid4()),
        "pack_id": "synthetic",
        "pack_digest": "sha256:" + "b" * 64,
        "installation_id": str(uuid4()),
        "binding_version": 1,
        "manifest": {
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.adapter",
            "version": "1",
            "distribution": "example-adapter",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "a" * 64,
            "capabilities": ["guest.configure", "guest.verify"],
            "required_bindings": ["server"],
            "required_parameters": [],
            "model_bindings": {},
        },
        "bindings": {"targets": {"server": "node.web"}, "parameters": {}, "image_profiles": {}},
    }
    admitted = RuntimePluginPin.model_validate(before)
    assert admitted.model_dump(mode="json") == before
    assert admitted.digest == canonical_digest(before)
