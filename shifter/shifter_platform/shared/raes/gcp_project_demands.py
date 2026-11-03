"""Project custody selection through released native planned-node accessors."""

from collections.abc import Mapping
from typing import Any

from raes_contracts.planning import RuntimeDomain, planned_node_spec

from shared.gcp_project_demands import MAX_PROJECT_SCOPE_REFERENCES, GcpProjectDemand, node_gcp_project_demands
from shared.raes.completion import load_serialized_plan


def planned_gcp_project_demands(serialized_plan: Mapping[str, Any]) -> tuple[GcpProjectDemand, ...]:
    """Project exact native scope identities; never select a project by pack or alias."""
    # Existing no-scope inputs keep their historical transport and require no
    # new native authority projection. Actual project demands always cross the
    # released plan/version gate below.
    raw: list[GcpProjectDemand] = []
    resources = _mapping(serialized_plan.get("resources", {}))
    for resource in resources.values():
        if not isinstance(resource, Mapping) or resource.get("resource_type") != "node":
            continue
        payload = _mapping(resource.get("payload", {}))
        node = _mapping(_mapping(payload.get("spec", {})).get("node", {}))
        runtime = node.get("runtime")
        if runtime is not None:
            raw.extend(node_gcp_project_demands(payload.get("node_name", ""), runtime))
    if not raw:
        return ()
    plan = load_serialized_plan(serialized_plan)
    demands: list[GcpProjectDemand] = []
    for resource in plan.resources.values():
        if resource.domain != RuntimeDomain.PROVISIONING or resource.resource_type != "node":
            continue
        node = planned_node_spec(resource)
        name = resource.payload.get("node_name")
        if node is None or not isinstance(name, str) or not name:
            raise ValueError("Registered project scope is unsupported")
        demands.extend(node_gcp_project_demands(name, node.get("runtime")))
    if len(demands) > MAX_PROJECT_SCOPE_REFERENCES or len({demand.scope_ref for demand in demands}) != len(demands):
        raise ValueError("Registered project scope is unsupported")
    return tuple(demands)


def _mapping(value: object) -> Mapping[str, Any]:
    """Malformed plan fragments never become an empty project declaration."""
    if not isinstance(value, Mapping):
        raise ValueError("Registered project scope is unsupported")
    return value
