"""Registered project references cannot cross native input custody boundaries."""

from copy import deepcopy
from uuid import uuid4

import pytest
from shifter_adapter_sdk.runtime import canonical_digest

from shared.gcp_range_projects import GcpProjectLease
from shared.raes.operation_input import RaesOperationInputError, parse_raes_operation_input
from shared.raes.operation_input_projects import project_bindings
from shared.runtime_plugin_preparation import RuntimePreparation
from tests.shared.raes.test_raes_operation_input import _built
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref


@pytest.fixture
def bound_input(baseline_ref):
    payload = _built()
    lease = GcpProjectLease(
        lease_id=uuid4(),
        source_operation_id=uuid4(),
        project_id="synthetic-project",
        project_number="123456789012",
        organization_uuid=uuid4(),
        range_uuid=uuid4(),
        range_id=payload["legacy_range_id"],
        request_id=uuid4(),
        plan_digest=canonical_digest(payload["plan"]),
        baseline=baseline_ref,
    )
    payload["gcp_projects"] = [lease.model_dump(mode="json")]
    return payload, lease


def test_closed_input_retains_exact_reference_and_empty_input_omits_field(bound_input):
    payload, lease = bound_input
    assert parse_raes_operation_input(payload).gcp_projects == (lease,)
    assert "gcp_projects" not in _built()


@pytest.mark.parametrize("change", ["plan", "range", "backend", "duplicate", "unknown", "null", "too-many"])
def test_changed_or_ambiguous_custody_is_rejected(bound_input, change):
    payload, _ = bound_input
    if change == "plan":
        payload["plan"]["resources"] = {}
    elif change == "range":
        payload["legacy_range_id"] += 1
    elif change == "backend":
        payload["range_backend"] = "ec2"
        payload["resource_generation"] = str(uuid4())
    elif change == "duplicate":
        payload["gcp_projects"] *= 2
    elif change == "unknown":
        payload["gcp_projects"][0]["provider_authority"] = "invented"
    elif change == "null":
        payload["gcp_projects"] = None
    else:
        payload["gcp_projects"] *= 9
    with pytest.raises(RaesOperationInputError, match="project binding"):
        parse_raes_operation_input(payload)


@pytest.mark.parametrize("field", ["source_operation_id", "request_id", "range_uuid", "organization_uuid"])
def test_multiple_projects_must_share_one_native_custody(bound_input, field):
    payload, _ = bound_input
    another = deepcopy(payload["gcp_projects"][0])
    another.update(project_id="another-project", lease_id=str(uuid4()))
    another[field] = str(uuid4())
    payload["gcp_projects"].append(another)
    with pytest.raises(RaesOperationInputError, match="project binding"):
        parse_raes_operation_input(payload)


def test_preparation_sidecar_and_top_level_project_references_must_match(bound_input):
    payload, lease = bound_input
    snapshot = RuntimePreparation(
        state="prepared",
        plan_digest=lease.plan_digest,
        pin_digest="sha256:" + "a" * 64,
        source_operation_id=lease.source_operation_id,
        input_digest="sha256:" + "b" * 64,
        encrypted_result="enc:v1:synthetic",
        cloud_projects=(lease,),
    )
    assert project_bindings(payload, snapshot) == (lease,)
    with pytest.raises(RaesOperationInputError, match="project binding"):
        project_bindings({**payload, "gcp_projects": []}, snapshot)
    with pytest.raises(ValueError):
        RuntimePreparation.model_validate({**snapshot.model_dump(mode="json"), "source_operation_id": str(uuid4())})


def test_held_project_cannot_be_transplanted_through_warm_activation(bound_input):
    from shared.warm_pool.activation_input import ACTIVATION_SCHEMA, ActivationInputError, parse_activation_input
    from tests.shared.test_warm_pool_activation_input import _payload

    payload, _lease = bound_input
    activation = _payload(raes_input=payload, schema=ACTIVATION_SCHEMA)
    with pytest.raises(ActivationInputError, match="not eligible for warm activation"):
        parse_activation_input(activation)
