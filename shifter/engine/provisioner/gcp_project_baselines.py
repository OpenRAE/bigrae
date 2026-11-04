"""Encrypted, create-only baseline artifacts in the existing configured GCS bucket."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from cryptography.fernet import Fernet
from shared.gcp_project_registration import GcpProjectRegistrationInput, GcpProjectRegistrationReceipt
from shared.gcp_range_projects import (
    MAX_BASELINE_CIPHERTEXT_BYTES,
    GcpBaselineRef,
    GcpProjectBaseline,
    GcpProjectLease,
    GcpProjectState,
    baseline_key,
    decode_project_baseline,
    require_project_parity,
)

from cloud.gcp.base import import_google_module

if TYPE_CHECKING:
    from gcp_project_inventory import ProjectInventory

_UNAVAILABLE = "Registered project baseline is unavailable"


class BaselineStore(Protocol):
    """One immutable object per native capture; nothing exposes a public URL."""

    def read(self, bucket: str, key: str, *, generation: str | None = None) -> tuple[bytes, str] | None:
        """Return bounded generation-bound ciphertext, or confirmed object absence."""
        ...

    def create(self, bucket: str, key: str, material: bytes) -> None:
        """Create if absent; preserve an earlier successful native retry's object."""
        ...


class _Blob(Protocol):
    """Only the SDK operations necessary to retain and read a baseline."""

    size: int | None
    generation: int | None

    def reload(self, *, timeout: int) -> None: ...
    def download_as_bytes(
        self, *, start: int, end: int, if_generation_match: int, raw_download: bool, timeout: int
    ) -> bytes: ...
    def upload_from_string(self, data: bytes, *, content_type: str, if_generation_match: int, timeout: int) -> None: ...


class _Bucket(Protocol):
    """SDK bucket access always takes a server-derived immutable capture key."""

    def blob(self, key: str, *, generation: int | None = None) -> _Blob: ...


class _Client(Protocol):
    """The existing Google object-storage client, not a new storage service."""

    def bucket(self, name: str) -> _Bucket: ...


class GcsBaselineStore:
    """Generation-conditional SDK reads/writes with a hard ciphertext byte bound."""

    def __init__(self, client: _Client | None = None) -> None:
        self._client = client or cast(_Client, import_google_module("google.cloud.storage").Client())

    def read(self, bucket: str, key: str, *, generation: str | None = None) -> tuple[bytes, str] | None:
        """Only provider NotFound means absence; a denied or incomplete read fails."""
        errors = import_google_module("google.api_core.exceptions")
        blob = self._client.bucket(bucket).blob(key, generation=int(generation) if generation is not None else None)
        try:
            blob.reload(timeout=30)
        except errors.NotFound:
            return None
        if blob.size is None or not 0 < blob.size <= MAX_BASELINE_CIPHERTEXT_BYTES or not blob.generation:
            raise ValueError(_UNAVAILABLE)
        observed_generation = blob.generation
        if generation is not None and str(observed_generation) != generation:
            raise ValueError(_UNAVAILABLE)
        material = blob.download_as_bytes(
            start=0, end=blob.size - 1, if_generation_match=observed_generation, raw_download=True, timeout=30
        )
        if len(material) != blob.size:
            raise ValueError(_UNAVAILABLE)
        return material, str(observed_generation)

    def create(self, bucket: str, key: str, material: bytes) -> None:
        """A duplicate Job cannot replace the first successful capture."""
        if not 0 < len(material) <= MAX_BASELINE_CIPHERTEXT_BYTES:
            raise ValueError(_UNAVAILABLE)
        errors = import_google_module("google.api_core.exceptions")
        try:
            self._client.bucket(bucket).blob(key).upload_from_string(
                material, content_type="application/octet-stream", if_generation_match=0, timeout=30
            )
        except errors.PreconditionFailed:
            return


def capture_project_baseline(
    original: GcpProjectRegistrationInput,
    operation_id: UUID,
    *,
    inventory: ProjectInventory,
    store: BaselineStore,
    cipher: Fernet,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> GcpProjectRegistrationReceipt:
    """Retain one stable original capture; retries never recapture a running range."""
    key = baseline_key(original.registration_id, operation_id)
    stored = store.read(original.bucket, key)
    if stored is None:
        state = inventory.read(original.project_id)
        # A changing project cannot produce an accepted baseline assembled from
        # different moments in its policy/object enumeration.
        require_project_parity(state, inventory.read(original.project_id))
        baseline = _captured_baseline(original, operation_id, state, now())
        material = cipher.encrypt(baseline.model_dump_json().encode())
        store.create(original.bucket, key, material)
        stored = store.read(original.bucket, key)
    if stored is None:
        raise ValueError(_UNAVAILABLE)
    material, generation = stored
    if len(material) > MAX_BASELINE_CIPHERTEXT_BYTES:
        raise ValueError(_UNAVAILABLE)
    baseline = decode_project_baseline(cipher.decrypt(material))
    if (baseline.registration_id, baseline.capture_operation_id, baseline.organization_uuid, baseline.project_id) != (
        original.registration_id,
        operation_id,
        original.organization_uuid,
        original.project_id,
    ):
        raise ValueError(_UNAVAILABLE)
    reference = GcpBaselineRef(
        registration_id=original.registration_id,
        capture_operation_id=operation_id,
        bucket=original.bucket,
        ciphertext_sha256="sha256:" + sha256(material).hexdigest(),
        ciphertext_bytes=len(material),
        generation=generation,
        state_digest=baseline.state.digest,
    )
    receipt = GcpProjectRegistrationReceipt(
        registration_id=original.registration_id,
        organization_uuid=original.organization_uuid,
        project_id=original.project_id,
        project_number=baseline.project_number,
        baseline=reference,
    )
    receipt.authorize(original, operation_id)
    return receipt


def _captured_baseline(
    original: GcpProjectRegistrationInput, operation_id: UUID, state: GcpProjectState, captured_at: datetime
) -> GcpProjectBaseline:
    """Derive the numeric identity from the independently read project resource."""
    name = state.project.get("name")
    if not isinstance(name, str) or not name.startswith("projects/"):
        raise ValueError(_UNAVAILABLE)
    return GcpProjectBaseline(
        schema_version="bigrae.gcp-project-baseline/v1",
        registration_id=original.registration_id,
        capture_operation_id=operation_id,
        organization_uuid=original.organization_uuid,
        project_id=original.project_id,
        project_number=name.removeprefix("projects/"),
        captured_at=captured_at,
        state=state,
    )


def load_project_baseline(lease: GcpProjectLease, *, store: BaselineStore, cipher: Fernet) -> GcpProjectBaseline:
    """Cleanup reads the original bucket and generation, independent of current config."""
    baseline = _read_retained_baseline(lease.baseline, store=store, cipher=cipher)
    baseline.authorize(lease)
    return baseline


def verify_project_baseline(
    original: GcpProjectRegistrationInput, *, inventory: ProjectInventory, store: BaselineStore, cipher: Fernet
) -> GcpProjectRegistrationReceipt:
    """Re-enable by reading the original capture; drift never creates a new baseline."""
    reference = original.baseline
    if reference is None:
        raise ValueError(_UNAVAILABLE)
    baseline = _read_retained_baseline(reference, store=store, cipher=cipher)
    if (baseline.organization_uuid, baseline.project_id) != (original.organization_uuid, original.project_id):
        raise ValueError(_UNAVAILABLE)
    require_project_parity(baseline.state, inventory.read(original.project_id))
    require_project_parity(baseline.state, inventory.read(original.project_id))
    return GcpProjectRegistrationReceipt(
        registration_id=original.registration_id,
        organization_uuid=original.organization_uuid,
        project_id=original.project_id,
        project_number=baseline.project_number,
        baseline=reference,
    )


def _read_retained_baseline(reference: GcpBaselineRef, *, store: BaselineStore, cipher: Fernet) -> GcpProjectBaseline:
    """Authenticate frozen object identity and the capture body before any provider work."""
    stored = store.read(reference.bucket, reference.key, generation=reference.generation)
    if stored is None or stored[1] != reference.generation:
        raise ValueError(_UNAVAILABLE)
    reference.verify_material(stored[0])
    baseline = decode_project_baseline(cipher.decrypt(stored[0]))
    if (baseline.registration_id, baseline.capture_operation_id, baseline.state.digest) != (
        reference.registration_id,
        reference.capture_operation_id,
        reference.state_digest,
    ):
        raise ValueError(_UNAVAILABLE)
    return baseline
