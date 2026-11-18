"""Bounded, application-independent custody and parity for registered GCP projects."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator
from shifter_adapter_sdk.runtime import ClosedModel, Digest, canonical_digest, decode_message

MAX_BASELINE_BYTES = 1_048_576
MAX_BASELINE_CIPHERTEXT_BYTES = 1_500_000
MAX_PROJECTS_PER_RANGE = 8
MAX_PROJECT_SERVICE_ACCOUNTS = 1024
MAX_PROJECT_SECRETS = 4096
ProjectID = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
ProjectNumber = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{5,19}$")]
JsonObject = dict[str, JsonValue]
_UNAVAILABLE = "Registered project binding is unavailable"
_INVALID = "Registered project metadata is invalid"


def baseline_key(registration_id: UUID, capture_operation_id: UUID) -> str:
    """One create-only capture per operation makes native worker retries idempotent."""
    return f"raes/project-baselines/{registration_id.hex}/{capture_operation_id.hex}/baseline.enc"


class GcpBaselineRef(ClosedModel):
    """Immutable encrypted object identity; the server fixes its bucket and key."""

    registration_id: UUID
    capture_operation_id: UUID
    bucket: Annotated[str, Field(strict=True, min_length=3, max_length=222, pattern=r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$")]
    ciphertext_sha256: Digest
    ciphertext_bytes: Annotated[int, Field(strict=True, gt=0, le=MAX_BASELINE_CIPHERTEXT_BYTES)]
    generation: Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,29}$")]
    state_digest: Digest

    @property
    def key(self) -> str:
        """Derive a fixed namespace from server-owned correlation and exact bytes."""
        return baseline_key(self.registration_id, self.capture_operation_id)

    def verify_material(self, material: bytes) -> None:
        """Refuse changed or oversized encrypted material without echoing values."""
        if (
            not isinstance(material, bytes)
            or len(material) != self.ciphertext_bytes
            or "sha256:" + hashlib.sha256(material).hexdigest() != self.ciphertext_sha256
        ):
            raise ValueError(_UNAVAILABLE)


class GcpProjectLease(ClosedModel):
    """Exact project and baseline retained by one admitted range lifetime."""

    binding_version: Literal[1] = 1
    lease_id: UUID
    source_operation_id: UUID
    project_id: ProjectID
    project_number: ProjectNumber
    organization_uuid: UUID
    range_uuid: UUID
    range_id: Annotated[int, Field(strict=True, gt=0)]
    request_id: UUID
    plan_digest: Digest
    baseline: GcpBaselineRef

    def authorize(self, *, request_id: UUID, range_id: int, plan_digest: str) -> None:
        """A retry cannot transplant a lease to another request, range or plan."""
        if (self.request_id, self.range_id, self.plan_digest) != (request_id, range_id, plan_digest):
            raise ValueError(_UNAVAILABLE)


class GcpProjectRestorationProof(ClosedModel):
    """Closed readback identity; a logical destroy is not a restoration proof."""

    lease_id: UUID
    registration_id: UUID
    baseline_state_digest: Digest
    observed_state_digest: Digest | None = None
    outcome: Literal["restored", "incomplete"]
    failure_code: Literal["", "readback-unavailable", "parity-mismatch", "unsupported"] = ""

    @model_validator(mode="after")
    def validate_outcome(self) -> GcpProjectRestorationProof:
        """Refuse a success claim without the exact original semantic state."""
        if self.outcome == "restored":
            if self.observed_state_digest != self.baseline_state_digest or self.failure_code:
                raise ValueError(_INVALID)
        elif not self.failure_code:
            raise ValueError(_INVALID)
        return self


class GcpServiceAccountState(ClosedModel):
    """Provider metadata only; existing private key material is never captured."""

    resource: JsonObject = Field(max_length=128, repr=False)
    policy: JsonObject = Field(max_length=16, repr=False)
    user_keys: list[JsonObject] = Field(default_factory=list, max_length=1024, repr=False)

    @model_validator(mode="after")
    def reject_private_keys(self) -> GcpServiceAccountState:
        """A mistaken create-key response must not become baseline metadata."""
        for key in self.user_keys:
            if {"privateKeyData", "private_key_data"} & key.keys():
                raise ValueError(_INVALID)
        return self


class GcpSecretState(ClosedModel):
    """Secret resource and version metadata, with no baseline payload access."""

    resource: JsonObject = Field(max_length=128, repr=False)
    policy: JsonObject = Field(max_length=16, repr=False)
    versions: dict[str, JsonObject] = Field(default_factory=dict, max_length=4096, repr=False)

    @model_validator(mode="after")
    def reject_payloads(self) -> GcpSecretState:
        """Access-secret responses cannot masquerade as version inventory."""
        if any("payload" in version for version in self.versions.values()):
            raise ValueError(_INVALID)
        return self


class GcpProjectState(ClosedModel):
    """Complete managed-surface record used for setup and baseline readback."""

    project: JsonObject = Field(max_length=128, repr=False)
    policy: JsonObject = Field(max_length=16, repr=False)
    service_accounts: dict[str, GcpServiceAccountState] = Field(
        default_factory=dict, max_length=MAX_PROJECT_SERVICE_ACCOUNTS, repr=False
    )
    secrets: dict[str, GcpSecretState] = Field(default_factory=dict, max_length=MAX_PROJECT_SECRETS, repr=False)

    @property
    def digest(self) -> str:
        """Bind every semantic value; provider change tokens are not desired state."""
        return canonical_digest(_state_comparison(self))


class GcpProjectBaseline(ClosedModel):
    """Encrypted artifact body, separate from the reference-only operation input."""

    schema_version: Literal["bigrae.gcp-project-baseline/v1"]
    registration_id: UUID
    capture_operation_id: UUID
    organization_uuid: UUID
    project_id: ProjectID
    project_number: ProjectNumber
    captured_at: AwareDatetime
    state: GcpProjectState = Field(repr=False)

    @model_validator(mode="after")
    def validate_inventory(self) -> GcpProjectBaseline:
        """Capture only the requested project inside the bounded artifact protocol."""
        if self.state.project.get("projectId") != self.project_id:
            raise ValueError(_INVALID)
        if self.state.project.get("name") != f"projects/{self.project_number}":
            raise ValueError(_INVALID)
        if len(self.model_dump_json().encode()) > MAX_BASELINE_BYTES:
            raise ValueError(_INVALID)
        return self

    def authorize(self, lease: GcpProjectLease) -> None:
        """A valid encrypted object still needs its original scope and lease binding."""
        expected = (
            lease.baseline.registration_id,
            lease.baseline.capture_operation_id,
            lease.organization_uuid,
            lease.project_id,
            lease.project_number,
            lease.baseline.state_digest,
        )
        actual = (
            self.registration_id,
            self.capture_operation_id,
            self.organization_uuid,
            self.project_id,
            self.project_number,
            self.state.digest,
        )
        if expected != actual:
            raise ValueError(_UNAVAILABLE)


def decode_project_baseline(raw: str | bytes) -> GcpProjectBaseline:
    """Refuse ambiguous, oversized or invalid private metadata with a bounded error."""
    try:
        return GcpProjectBaseline.model_validate(decode_message(raw, limit=MAX_BASELINE_BYTES))
    except Exception:  # noqa: BLE001  # provider metadata and validation input echoes never cross this boundary
        raise ValueError(_INVALID) from None


def require_project_parity(expected: GcpProjectState, actual: GcpProjectState) -> None:
    """Fail on any managed resource, permission, identity or value difference."""
    if expected.digest != actual.digest:
        raise ValueError("Registered project parity failed")


def _resource_comparison(resource: JsonObject) -> JsonObject:
    """Exclude only top-level provider change tokens; authored nested keys remain."""
    return {key: value for key, value in resource.items() if key not in {"etag", "updateTime"}}


def _sorted_field(value: JsonObject, name: str) -> None:
    """Canonicalize a documented set-valued field without deleting duplicates."""
    items = value.get(name)
    if items is not None:
        if not isinstance(items, list):
            raise ValueError(_INVALID)
        value[name] = sorted(items, key=canonical_digest)


def _policy_comparison(policy: JsonObject) -> JsonObject:
    """IAM set ordering and format versions cannot hide changed grants or conditions."""
    result = deepcopy(policy)
    result.pop("etag", None)
    version = result.get("version", 0)
    if type(version) is not int or version not in (0, 1, 3):
        raise ValueError(_INVALID)
    result["version"] = 3
    _nested_policy_sets(result, "bindings", "members")
    audit = result.get("auditConfigs", [])
    if not isinstance(audit, list):
        raise ValueError(_INVALID)
    for service in audit:
        if not isinstance(service, dict):
            raise ValueError(_INVALID)
        _nested_policy_sets(service, "auditLogConfigs", "exemptedMembers")
    _sorted_field(result, "auditConfigs")
    return result


def _nested_policy_sets(policy: JsonObject, name: str, members: str) -> None:
    """Retain complete row bodies while sorting only their defined member sets."""
    rows = policy.get(name, [])
    if not isinstance(rows, list):
        raise ValueError(_INVALID)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(_INVALID)
        _sorted_field(row, members)
    _sorted_field(policy, name)


def _state_comparison(state: GcpProjectState) -> JsonObject:
    """Preserve all resource identities and metadata outside documented change tokens."""
    accounts: JsonObject = {
        name: {
            "resource": _resource_comparison(account.resource),
            "policy": _policy_comparison(account.policy),
            "user_keys": sorted((_resource_comparison(key) for key in account.user_keys), key=canonical_digest),
        }
        for name, account in state.service_accounts.items()
    }
    secrets: JsonObject = {
        name: {
            "resource": _resource_comparison(secret.resource),
            "policy": _policy_comparison(secret.policy),
            "versions": {version: _resource_comparison(metadata) for version, metadata in secret.versions.items()},
        }
        for name, secret in state.secrets.items()
    }
    return {
        "project": _resource_comparison(state.project),
        "policy": _policy_comparison(state.policy),
        "service_accounts": accounts,
        "secrets": secrets,
    }
