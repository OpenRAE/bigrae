"""Project custody and parity preserve values across the worker boundary."""

import hashlib
from uuid import uuid4

import pytest

from shared.gcp_range_projects import (
    GcpBaselineRef,
    GcpProjectLease,
    GcpProjectState,
    GcpSecretState,
    GcpServiceAccountState,
    require_project_parity,
)


@pytest.fixture
def baseline_ref():
    material = b"synthetic encrypted baseline"
    return GcpBaselineRef(
        bucket="synthetic-private-assets",
        registration_id=uuid4(),
        capture_operation_id=uuid4(),
        ciphertext_sha256="sha256:" + hashlib.sha256(material).hexdigest(),
        ciphertext_bytes=len(material),
        generation="12345",
        state_digest="sha256:" + "b" * 64,
    )


def test_baseline_reference_cannot_redirect_storage_or_change_bytes(baseline_ref):
    assert baseline_ref.key.startswith(f"raes/project-baselines/{baseline_ref.registration_id.hex}/")
    baseline_ref.verify_material(b"synthetic encrypted baseline")
    with pytest.raises(ValueError):
        baseline_ref.verify_material(b"different")
    with pytest.raises(ValueError):
        GcpBaselineRef.model_validate({**baseline_ref.model_dump(), "key": "other/path"})


def test_lease_is_bound_to_original_range_request_and_plan(baseline_ref):
    request, organization = uuid4(), uuid4()
    lease = GcpProjectLease(
        lease_id=uuid4(),
        project_id="synthetic-project",
        project_number="123456789012",
        organization_uuid=organization,
        range_uuid=uuid4(),
        range_id=7,
        request_id=request,
        plan_digest="sha256:" + "c" * 64,
        baseline=baseline_ref,
    )
    lease.authorize(request_id=request, range_id=7, plan_digest=lease.plan_digest)
    with pytest.raises(ValueError):
        lease.authorize(request_id=uuid4(), range_id=7, plan_digest=lease.plan_digest)
    with pytest.raises(ValueError):
        lease.authorize(request_id=request, range_id=8, plan_digest=lease.plan_digest)
    with pytest.raises(ValueError):
        lease.authorize(request_id=request, range_id=7, plan_digest="sha256:" + "f" * 64)


@pytest.fixture
def state():
    return GcpProjectState(
        project={"projectId": "synthetic-project", "name": "projects/123456789012", "labels": {"etag": "authored"}},
        policy={
            "version": 3,
            "etag": "current",
            "bindings": [
                {"role": "roles/viewer", "members": ["user:b@example.test", "user:a@example.test"]},
                {"role": "roles/secretmanager.secretAccessor", "members": ["serviceAccount:reader@example.test"]},
            ],
        },
        service_accounts={
            "reader@example.test": GcpServiceAccountState(
                resource={"email": "reader@example.test", "uniqueId": "123", "disabled": False},
                policy={"version": 3, "bindings": [], "etag": "old"},
                user_keys=[],
            )
        },
        secrets={
            "example": GcpSecretState(
                resource={
                    "name": "projects/123456789012/secrets/example",
                    "createTime": "original",
                    "etag": "old",
                    "replication": {"automatic": {}},
                },
                policy={"version": 3, "bindings": []},
                versions={
                    "1": {"name": "projects/123456789012/secrets/example/versions/1", "state": "ENABLED", "etag": "old"}
                },
            )
        },
    )


def test_parity_ignores_only_change_tokens_and_semantic_iam_set_order(state):
    actual = state.model_copy(deep=True)
    actual.policy["etag"] = "changed"
    actual.policy["bindings"].reverse()
    actual.policy["bindings"][1]["members"].reverse()
    actual.secrets["example"].resource["etag"] = "changed"
    actual.secrets["example"].versions["1"]["etag"] = "changed"
    require_project_parity(state, actual)
    assert state.digest == actual.digest


@pytest.mark.parametrize(
    "change", ["role", "member", "condition", "account-id", "secret-state", "new-secret", "label-etag", "incarnation"]
)
def test_every_security_or_resource_difference_fails_parity(state, change):
    actual = state.model_copy(deep=True)
    if change == "role":
        actual.policy["bindings"][0]["role"] = "roles/owner"
    elif change == "member":
        actual.policy["bindings"][0]["members"].append("allUsers")
    elif change == "condition":
        actual.policy["bindings"][0]["condition"] = {"title": "changed", "expression": "true"}
    elif change == "account-id":
        actual.service_accounts["reader@example.test"].resource["uniqueId"] = "456"
    elif change == "secret-state":
        actual.secrets["example"].versions["1"]["state"] = "DISABLED"
    elif change == "new-secret":
        actual.secrets["unexpected"] = actual.secrets["example"]
    elif change == "label-etag":
        actual.project["labels"]["etag"] = "changed authored value"
    else:
        actual.secrets["example"].resource["createTime"] = "recreated"
    with pytest.raises(ValueError, match="parity"):
        require_project_parity(state, actual)


def test_baseline_metadata_cannot_include_secret_payload_or_private_key_data(state):
    raw = state.model_dump(mode="json")
    raw["secrets"]["example"]["versions"]["1"]["payload"] = {"data": "private"}
    with pytest.raises(ValueError):
        GcpProjectState.model_validate(raw)
    raw = state.model_dump(mode="json")
    raw["service_accounts"]["reader@example.test"]["user_keys"] = [{"privateKeyData": "private"}]
    with pytest.raises(ValueError):
        GcpProjectState.model_validate(raw)


@pytest.mark.parametrize("change", ["missing-readback", "drift", "success-error", "incomplete-no-error"])
def test_restoration_requires_exact_positive_readback(baseline_ref, change):
    from shared.gcp_range_projects import GcpProjectRestorationProof

    fields = {
        "lease_id": uuid4(),
        "registration_id": baseline_ref.registration_id,
        "baseline_state_digest": baseline_ref.state_digest,
        "observed_state_digest": baseline_ref.state_digest,
        "outcome": "restored",
    }
    assert GcpProjectRestorationProof.model_validate(fields).outcome == "restored"
    if change == "missing-readback":
        fields.pop("observed_state_digest")
    elif change == "drift":
        fields["observed_state_digest"] = "sha256:" + "f" * 64
    elif change == "success-error":
        fields["failure_code"] = "readback-unavailable"
    else:
        fields["outcome"] = "incomplete"
    with pytest.raises(ValueError):
        GcpProjectRestorationProof.model_validate(fields)


def test_baseline_decode_is_bounded_and_binds_original_project_organization_and_lease(state, baseline_ref):
    from datetime import UTC, datetime

    from shared.gcp_range_projects import GcpProjectBaseline, decode_project_baseline

    baseline = GcpProjectBaseline(
        schema_version="bigrae.gcp-project-baseline/v1",
        registration_id=baseline_ref.registration_id,
        capture_operation_id=baseline_ref.capture_operation_id,
        organization_uuid=uuid4(),
        project_id="synthetic-project",
        project_number="123456789012",
        captured_at=datetime.now(UTC),
        state=state,
    )
    assert decode_project_baseline(baseline.model_dump_json()) == baseline
    reference = baseline_ref.model_copy(update={"state_digest": state.digest})
    lease = GcpProjectLease(
        lease_id=uuid4(),
        project_id=baseline.project_id,
        project_number=baseline.project_number,
        organization_uuid=baseline.organization_uuid,
        range_uuid=uuid4(),
        range_id=1,
        request_id=uuid4(),
        plan_digest="sha256:" + "c" * 64,
        baseline=reference,
    )
    baseline.authorize(lease)
    for changed in (
        lease.model_copy(update={"organization_uuid": uuid4()}),
        lease.model_copy(update={"project_id": "different-project"}),
        lease.model_copy(update={"baseline": reference.model_copy(update={"capture_operation_id": uuid4()})}),
    ):
        with pytest.raises(ValueError, match="unavailable"):
            baseline.authorize(changed)
    for raw in ('{"state":{},"state":{}}', "x" * 1_048_577):
        with pytest.raises(ValueError, match="invalid"):
            decode_project_baseline(raw)
