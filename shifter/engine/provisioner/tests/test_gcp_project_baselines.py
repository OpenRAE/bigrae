"""Synthetic capture, retry and cleanup prove encrypted immutable baseline custody."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from shared.gcp_project_registration import GcpProjectRegistrationInput
from shared.gcp_range_projects import GcpProjectLease, GcpProjectState, decode_project_baseline

from gcp_project_baselines import capture_project_baseline, load_project_baseline


class Store:
    def __init__(self):
        self.objects = {}
        self.reads = []

    def read(self, bucket, key, *, generation=None):
        self.reads.append((bucket, key, generation))
        return self.objects.get((bucket, key))

    def create(self, bucket, key, material):
        self.objects.setdefault((bucket, key), (material, "12345"))


@pytest.fixture
def capture():
    original = GcpProjectRegistrationInput(
        registration_id=uuid4(),
        organization_uuid=uuid4(),
        project_id="synthetic-project",
        bucket="synthetic-private-assets",
        protected_project_ids=["synthetic-control"],
    )
    state = GcpProjectState(
        project={
            "projectId": "synthetic-project",
            "name": "projects/123456789012",
            "state": "ACTIVE",
            "labels": {"example": "private-metadata"},
        },
        policy={"version": 3, "bindings": []},
    )
    return original, uuid4(), Mock(read=Mock(return_value=state)), Store(), Fernet(Fernet.generate_key())


def run(capture):
    original, operation_id, inventory, store, cipher = capture
    return capture_project_baseline(original, operation_id, inventory=inventory, store=store, cipher=cipher)


def lease(capture, receipt):
    original = capture[0]
    return GcpProjectLease(
        lease_id=uuid4(),
        project_id=receipt.project_id,
        project_number=receipt.project_number,
        organization_uuid=original.organization_uuid,
        range_uuid=uuid4(),
        range_id=1,
        request_id=uuid4(),
        plan_digest="sha256:" + "a" * 64,
        baseline=receipt.baseline,
    )


def test_capture_encrypts_metadata_and_emits_only_an_immutable_reference(capture):
    receipt = run(capture)
    original, operation_id, inventory, store, cipher = capture
    assert inventory.read.call_count == 2
    assert len(store.objects) == 1
    material, generation = store.objects[(original.bucket, receipt.baseline.key)]
    assert b"private-metadata" not in material
    assert "private-metadata" not in receipt.model_dump_json()
    baseline = decode_project_baseline(cipher.decrypt(material))
    assert baseline.state.project["labels"] == {"example": "private-metadata"}
    assert baseline.capture_operation_id == operation_id
    assert receipt.baseline.generation == generation
    receipt.baseline.verify_material(material)


def test_native_retry_uses_original_capture_without_reinventory(capture):
    receipt = run(capture)
    capture[2].read.side_effect = AssertionError("A retry must not capture the range overlay as a new baseline")
    assert run(capture) == receipt
    assert len(capture[3].objects) == 1


def test_unstable_inventory_is_refused_before_baseline_write(capture):
    original, operation_id, inventory, store, cipher = capture
    different = inventory.read.return_value.model_copy(deep=True)
    different.policy["bindings"] = [{"role": "roles/owner", "members": ["allUsers"]}]
    inventory.read.side_effect = [inventory.read.return_value, different]
    with pytest.raises(ValueError, match="parity"):
        capture_project_baseline(original, operation_id, inventory=inventory, store=store, cipher=cipher)
    assert not store.objects


def test_cleanup_reads_exact_original_bucket_generation_and_digest(capture):
    receipt = run(capture)
    binding = lease(capture, receipt)
    baseline = load_project_baseline(binding, store=capture[3], cipher=capture[4])
    assert baseline.state.digest == receipt.baseline.state_digest
    assert capture[3].reads[-1] == (receipt.baseline.bucket, receipt.baseline.key, receipt.baseline.generation)


@pytest.mark.parametrize("change", ["missing", "generation", "bytes", "organization", "project", "digest"])
def test_changed_or_transplanted_baseline_never_authorizes_cleanup(capture, change):
    receipt = run(capture)
    binding = lease(capture, receipt)
    store, cipher = capture[3:]
    key = (receipt.baseline.bucket, receipt.baseline.key)
    if change == "missing":
        store.objects.clear()
    elif change == "generation":
        store.objects[key] = (store.objects[key][0], "99999")
    elif change == "bytes":
        store.objects[key] = (b"changed", store.objects[key][1])
    elif change == "organization":
        binding = binding.model_copy(update={"organization_uuid": uuid4()})
    elif change == "project":
        binding = binding.model_copy(update={"project_id": "another-project"})
    else:
        binding = binding.model_copy(
            update={"baseline": binding.baseline.model_copy(update={"state_digest": "sha256:" + "f" * 64})}
        )
    with pytest.raises(ValueError, match="unavailable"):
        load_project_baseline(binding, store=store, cipher=cipher)


@pytest.fixture
def sdk_errors(monkeypatch):
    import sys
    from types import ModuleType

    errors = ModuleType("google.api_core.exceptions")
    errors.NotFound = type("NotFound", (Exception,), {})
    errors.PreconditionFailed = type("PreconditionFailed", (Exception,), {})
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", errors)
    return errors


def test_gcs_store_reads_bounded_exact_generation_and_create_only(sdk_errors):
    from gcp_project_baselines import GcsBaselineStore

    blob = Mock(size=7, generation=123, download_as_bytes=Mock(return_value=b"example"))
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    store = GcsBaselineStore(client)
    assert store.read("synthetic-assets", "original/key", generation="123") == (b"example", "123")
    client.bucket.return_value.blob.assert_called_with("original/key", generation=123)
    blob.download_as_bytes.assert_called_once_with(
        start=0, end=6, if_generation_match=123, raw_download=True, timeout=30
    )
    store.create("synthetic-assets", "original/key", b"example")
    blob.upload_from_string.assert_called_once_with(
        b"example", content_type="application/octet-stream", if_generation_match=0, timeout=30
    )
    blob.upload_from_string.side_effect = sdk_errors.PreconditionFailed()
    store.create("synthetic-assets", "original/key", b"example")


@pytest.mark.parametrize("failure", ["oversized", "generation", "short-read", "read-denied", "download-denied"])
def test_gcs_store_never_trusts_changed_or_incomplete_material(sdk_errors, failure):
    from gcp_project_baselines import GcsBaselineStore

    blob = Mock(size=7, generation=123, download_as_bytes=Mock(return_value=b"example"))
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    if failure == "oversized":
        blob.size = 1_500_001
    elif failure == "generation":
        blob.generation = 456
    elif failure == "short-read":
        blob.download_as_bytes.return_value = b"short"
    elif failure == "read-denied":
        blob.reload.side_effect = PermissionError()
    else:
        blob.download_as_bytes.side_effect = PermissionError()
    with pytest.raises((ValueError, PermissionError)):
        GcsBaselineStore(client).read("synthetic-assets", "original/key", generation="123")


def test_only_confirmed_not_found_allows_first_capture(sdk_errors):
    from gcp_project_baselines import GcsBaselineStore

    client = Mock()
    client.bucket.return_value.blob.return_value.reload.side_effect = sdk_errors.NotFound()
    assert GcsBaselineStore(client).read("synthetic-assets", "original/key") is None


def test_reenable_verifies_original_baseline_and_never_recaptures_drift(capture):
    from gcp_project_baselines import verify_project_baseline

    receipt = run(capture)
    original, _operation_id, inventory, store, cipher = capture
    original = original.model_copy(update={"baseline": receipt.baseline})
    assert verify_project_baseline(original, inventory=inventory, store=store, cipher=cipher) == receipt
    inventory.read.return_value.policy["bindings"] = [{"role": "roles/owner", "members": ["allUsers"]}]
    with pytest.raises(ValueError, match="parity"):
        verify_project_baseline(original, inventory=inventory, store=store, cipher=cipher)
    assert len(store.objects) == 1
