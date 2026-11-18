"""Contract tests for the provisioner operation transport envelope (#1834)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from shared.operation_envelope import (
    ACCEPTED_CONTRACT_VERSIONS,
    CONTRACT_VERSION,
    MAX_ENVELOPE_BYTES,
    MAX_RAES_INPUT_BYTES,
    OperationEnvelopeError,
    build_operation_envelope,
    canonical_payload_digest,
    validate_operation_envelope,
)

OID = str(uuid4())
RID = str(uuid4())


def _valid(**overrides):
    base = {
        "contract_version": CONTRACT_VERSION,
        "operation_id": OID,
        "request_id": RID,
        "resource": "range",
        "operation": "provision",
        "payload": {"spec": "x"},
    }
    base.update(overrides)
    return base


class TestValidateOperationEnvelope:
    def test_round_trips_a_valid_envelope(self):
        env = validate_operation_envelope(_valid())
        assert env == _valid()
        assert CONTRACT_VERSION in ACCEPTED_CONTRACT_VERSIONS

    def test_build_helper_normalizes_uuid_objects(self):
        env = build_operation_envelope(
            operation_id=uuid4(), request_id=uuid4(), resource="ngfw", operation="deprovision", payload={}
        )
        assert env["resource"] == "ngfw"
        assert env["operation"] == "deprovision"

    def test_rejects_unexpected_key(self):
        candidate = {**_valid(), "extra": 1}
        with pytest.raises(OperationEnvelopeError, match="unexpected"):
            validate_operation_envelope(candidate)

    def test_rejects_missing_key(self):
        bad = _valid()
        del bad["payload"]
        with pytest.raises(OperationEnvelopeError, match="missing"):
            validate_operation_envelope(bad)

    @pytest.mark.parametrize("field", ["operation_id", "request_id"])
    def test_rejects_non_uuid_correlation(self, field):
        candidate = _valid(**{field: "not-a-uuid"})
        with pytest.raises(OperationEnvelopeError, match="UUID"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_resource(self):
        candidate = _valid(resource="database")
        with pytest.raises(OperationEnvelopeError, match="resource"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_operation(self):
        candidate = _valid(operation="exec")
        with pytest.raises(OperationEnvelopeError, match="operation"):
            validate_operation_envelope(candidate)

    def test_rejects_unknown_contract_version(self):
        candidate = _valid(contract_version="999")
        with pytest.raises(OperationEnvelopeError, match="contract_version"):
            validate_operation_envelope(candidate)

    def test_rejects_non_object_payload(self):
        candidate = _valid(payload=["not", "an", "object"])
        with pytest.raises(OperationEnvelopeError, match="payload"):
            validate_operation_envelope(candidate)

    def test_rejects_oversized_envelope(self):
        candidate = _valid(payload={"blob": "x" * (MAX_ENVELOPE_BYTES + 1)})
        with pytest.raises(OperationEnvelopeError, match="exceeds"):
            validate_operation_envelope(candidate)


class TestCanonicalPayloadDigest:
    def test_is_order_independent(self):
        assert canonical_payload_digest({"a": 1, "b": 2}) == canonical_payload_digest({"b": 2, "a": 1})

    def test_changes_with_content(self):
        assert canonical_payload_digest({"a": 1}) != canonical_payload_digest({"a": 2})

    def test_is_sha256_prefixed(self):
        digest = canonical_payload_digest({"a": 1})
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64


def test_authority_version_requires_bound_digest_without_bearer_or_cookie_fields():
    digest = canonical_payload_digest({"credential_reference": str(uuid4())})
    envelope = _valid(contract_version="2", authority_digest=digest)
    assert validate_operation_envelope(envelope) == envelope
    for invalid in (None, "secret-token", "sha256:" + "A" * 64):
        with pytest.raises(OperationEnvelopeError):
            validate_operation_envelope({**envelope, "authority_digest": invalid})
    with pytest.raises(OperationEnvelopeError):
        validate_operation_envelope(_valid(contract_version="2"))
    with pytest.raises(OperationEnvelopeError):
        validate_operation_envelope({**envelope, "session_key": "SECRET_MARKER"})
    with pytest.raises(OperationEnvelopeError):
        validate_operation_envelope(_valid(authority_digest=digest))


def test_native_plan_inputs_have_a_bounded_larger_budget_without_growing_other_envelopes():
    payload = {"plan": {"kind": "raes_provisioning_plan", "resources": {}, "description": "x" * MAX_ENVELOPE_BYTES}}
    assert validate_operation_envelope(_valid(resource="raes-range", payload=payload))["payload"] == payload
    with pytest.raises(OperationEnvelopeError, match="exceeds"):
        validate_operation_envelope(_valid(payload=payload))
    with pytest.raises(OperationEnvelopeError, match="exceeds"):
        validate_operation_envelope(
            _valid(
                resource="raes-range", payload={"plan": {"kind": "foreign", "description": "x" * MAX_ENVELOPE_BYTES}}
            )
        )
    payload["plan"]["description"] = "x" * MAX_RAES_INPUT_BYTES
    with pytest.raises(OperationEnvelopeError, match="exceeds"):
        validate_operation_envelope(_valid(resource="raes-range", payload=payload))


@pytest.mark.parametrize("operation", ["provision", "destroy"])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_native_input_budget_has_an_exact_byte_boundary(operation, offset):
    candidate = _valid(
        resource="raes-range",
        operation=operation,
        payload={"plan": {"kind": "raes_provisioning_plan", "description": ""}},
    )
    overhead = len(json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode())
    candidate["payload"]["plan"]["description"] = "x" * (16 * 1024**2 + offset - overhead)
    if offset > 0:
        with pytest.raises(OperationEnvelopeError, match="exceeds 16777216 bytes"):
            validate_operation_envelope(candidate)
    else:
        assert validate_operation_envelope(candidate) == candidate
