"""Registered-project selection follows the released native node contract."""

from copy import deepcopy

import pytest
import yaml
from raes.scenarios import load_scenario
from raes_contracts.planning import planned_node_spec
from raes_runtime import RuntimeManager

from shared.gcp_project_demands import GcpProjectDemand, node_gcp_project_demands
from shared.raes.gcp_project_demands import planned_gcp_project_demands
from shared.raes.runtime_target import create_shifter_backend_target, serialize_provisioning_plan
from tests.shared.raes.test_realizability import _cloud_contract


class NeverDispatch:
    def realize(self, *args, **kwargs):
        raise AssertionError("Project selection cannot dispatch")


@pytest.fixture
def native_plan(tmp_path):
    path = _cloud_contract(tmp_path)
    document = yaml.safe_load(path.read_text())
    scope = document["nodes"]["web"]["runtime"]["identity_authorities"][0]["resource_scopes"][0]
    scope.update(native_id="synthetic-project", incarnation_id="123456789012")
    path.write_text(yaml.safe_dump(document))
    scenario = load_scenario(path)
    target = create_shifter_backend_target(port=NeverDispatch(), scenario=scenario)
    # Native compilation remains independent of capability acceptance. This
    # exercises custody extraction only; no cloud capability claim is enabled.
    plan = RuntimeManager(target).plan(scenario).provisioning
    return plan, serialize_provisioning_plan(plan)


def test_project_selection_matches_public_accessor_and_preserves_native_reference(native_plan):
    plan, serialized = native_plan
    node = planned_node_spec(plan.resources["provision.node.web"])
    expected = (
        GcpProjectDemand(
            "nodes.web.runtime.identity_authorities.cloud-iam.resource_scopes.project",
            "synthetic-project",
            "123456789012",
        ),
    )
    assert node_gcp_project_demands("web", node["runtime"]) == expected
    assert planned_gcp_project_demands(serialized) == expected


@pytest.mark.parametrize(
    "change",
    [
        "missing-project",
        "foreign-provider",
        "wrong-kind",
        "incarnation",
        "scopes-shape",
        "authority-shape",
        "duplicate",
    ],
)
def test_unresolved_or_malformed_scope_cannot_become_an_empty_selection(native_plan, change):
    _plan, serialized = native_plan
    runtime = deepcopy(serialized["resources"]["provision.node.web"]["payload"]["spec"]["node"]["runtime"])
    authority = runtime["identity_authorities"][0]
    scope = authority["resource_scopes"][0]
    if change == "missing-project":
        scope["native_id"] = ""
    elif change == "foreign-provider":
        scope["provider"] = "aws"
    elif change == "wrong-kind":
        scope["scope_kind"] = "organization"
    elif change == "incarnation":
        scope["incarnation_id"] = "invalid"
    elif change == "scopes-shape":
        authority["resource_scopes"] = {}
    elif change == "authority-shape":
        runtime["identity_authorities"] = None
    else:
        authority["resource_scopes"].append(scope)
    with pytest.raises(ValueError, match="unsupported"):
        node_gcp_project_demands("web", runtime)


def test_no_cloud_runtime_retains_empty_custody_selection():
    assert node_gcp_project_demands("web", None) == ()
    assert node_gcp_project_demands("web", {}) == ()
    with pytest.raises(ValueError, match="unsupported"):
        node_gcp_project_demands("web", False)
