"""Real native input/result parsers around synthetic database and Google SDK ports."""

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from shared.gcp_project_registration import GcpProjectRegistrationInput
from shared.operation_envelope import build_operation_envelope

from gcp_project_registration import run_project_registration
from tests.test_gcp_project_baselines import sdk_errors as sdk_errors
from tests.test_gcp_project_inventory import Response, Session
from tests.test_gcp_project_inventory import routes as routes


@pytest.fixture
def native_worker(monkeypatch, routes, sdk_errors):
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for key, value in {
        "DB_HOST": "127.0.0.1",
        "DB_USER": "test",
        "DB_NAME": "synthetic",
        "DB_PASSWORD": "test",
        "DB_AUTH_MODE": "password",
    }.items():
        monkeypatch.setenv(key, value)
    original = GcpProjectRegistrationInput(
        registration_id=uuid4(),
        organization_uuid=uuid4(),
        project_id="synthetic-project",
        bucket="synthetic-private-assets",
        protected_project_ids=["synthetic-control"],
    )
    operation_id = uuid4()
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=original.registration_id,
        resource="range-project",
        operation="register",
        payload=original.model_dump(mode="json"),
    )
    cursor, connection = MagicMock(), MagicMock()
    cursor.fetchone.return_value = (
        str(operation_id),
        str(original.registration_id),
        "range-project",
        "register",
        "1",
        envelope,
    )
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr("psycopg.connect", lambda **kwargs: connection)
    auth, transport, storage = (
        ModuleType("google.auth"),
        ModuleType("google.auth.transport.requests"),
        ModuleType("google.cloud.storage"),
    )
    auth.default = lambda **kwargs: (object(), None)
    transport.AuthorizedSession = lambda _credential: Session(routes)

    class Blob:
        material = None
        generation = 1

        @property
        def size(self):
            return len(self.material) if self.material is not None else None

        def reload(self, **kwargs):
            if self.material is None:
                raise sdk_errors.NotFound()

        def upload_from_string(self, material, **kwargs):
            assert kwargs["if_generation_match"] == 0
            self.material = material

        def download_as_bytes(self, **kwargs):
            assert kwargs["if_generation_match"] == self.generation
            return self.material

    blob = Blob()
    storage_client = MagicMock()
    storage_client.bucket.return_value.blob.return_value = blob
    storage.Client = lambda: storage_client
    for module in (auth, transport, storage):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return original, operation_id, cursor, routes


def appended(cursor):
    writes = [
        call.args[1]
        for call in cursor.execute.call_args_list
        if "INSERT INTO engine_operation_result_inbox" in call.args[0]
    ]
    assert len(writes) == 1
    return writes[0], json.loads(writes[0][-1])


def test_native_worker_uses_exact_input_and_appends_reference_only_result(native_worker, capsys):
    original, operation_id, cursor, _routes = native_worker
    run_project_registration(str(original.registration_id), str(operation_id))
    params, envelope = appended(cursor)
    assert params[0:4] == (str(operation_id), str(original.registration_id), "range-project", "register")
    assert params[6] == "gcp_project_ready"
    assert envelope["payload"]["baseline"]["capture_operation_id"] == str(operation_id)
    assert "service_accounts" not in json.dumps(envelope)
    assert capsys.readouterr().out == ""


def test_provider_error_appends_bounded_failure_without_metadata_or_false_empty_inventory(native_worker, capsys):
    original, operation_id, cursor, routes = native_worker
    key = next(key for key in routes if key[0].endswith("/secrets"))
    routes[key] = Response({"error": "private provider diagnostic"}, status=403)
    with pytest.raises(ValueError, match=r"^Registered project capture failed$"):
        run_project_registration(str(original.registration_id), str(operation_id))
    params, envelope = appended(cursor)
    assert params[6] == "gcp_project_failed"
    assert envelope["payload"] == {
        "reason_code": "cloud_operation_failed",
        "diagnostic": "Registered project capture failed",
    }
    assert capsys.readouterr().out == ""


def test_changed_control_project_is_refused_before_provider_inventory(native_worker, monkeypatch):
    original, operation_id, cursor, routes = native_worker
    monkeypatch.setenv("GCP_PROJECT_ID", original.project_id)
    routes.clear()
    with pytest.raises(ValueError, match=r"^Registered project capture failed$"):
        run_project_registration(str(original.registration_id), str(operation_id))
    assert appended(cursor)[0][6] == "gcp_project_failed"


@pytest.mark.parametrize("source", ["image", "machine-image"])
def test_all_configured_keyed_image_projects_are_protected_before_inventory(native_worker, monkeypatch, source):
    from config._gce_image_keys import _load_gce_image_key_profiles
    from config._gce_profile import GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST, GCE_PARTICIPANT_READINESS_CONTRACT_V1

    original, operation_id, cursor, _routes = native_worker
    profile = {
        "machine_type": "n2-standard-8",
        "bootstrap_capability": GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        "participant_container_name": "synthetic-desktop",
        "participant_username": "operator",
        "host_ssh_username": "hostadmin",
        "participant_readiness_contract": GCE_PARTICIPANT_READINESS_CONTRACT_V1,
        "participant_readiness_manifest_sha256": "a" * 64,
    }
    if source == "image":
        profile.update(
            source_image=f"projects/{original.project_id}/global/images/synthetic-host",
            disk_size_gb=220,
            disk_type="pd-balanced",
        )
    else:
        profile["source_machine_image"] = f"projects/{original.project_id}/global/machineImages/synthetic-host"
    monkeypatch.setenv("GCP_RANGE_IMAGE_KEY_PROFILES_JSON", json.dumps({"kali": {"synthetic-host": profile}}))
    # Verify a complete valid profile, rather than exercising a malformed-config refusal.
    assert _load_gce_image_key_profiles()["kali"]["synthetic-host"].machine_type == "n2-standard-8"
    inventory_factory = MagicMock(side_effect=AssertionError("Protected projects must not reach inventory"))
    monkeypatch.setattr("gcp_project_inventory.GcpProjectInventory", inventory_factory)
    with pytest.raises(ValueError, match=r"^Registered project capture failed$"):
        run_project_registration(str(original.registration_id), str(operation_id))
    assert appended(cursor)[0][6] == "gcp_project_failed"
    inventory_factory.assert_not_called()
