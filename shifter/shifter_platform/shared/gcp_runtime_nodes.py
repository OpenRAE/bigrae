"""Identify native cloud nodes and retain every authored guest demand in worker projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.gcp_runtime_types import UNSUPPORTED, records, token


def native_cloud_nodes(plan: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Read the public planned-node payload, retaining its native reference names."""
    result = []
    for address, resource in plan.get("resources", {}).items():
        if resource.get("resource_type") != "node":
            continue
        payload = resource["payload"]
        runtime = payload.get("spec", {}).get("node", {}).get("runtime")
        if runtime is None:
            continue
        if not isinstance(runtime, dict):
            raise ValueError(UNSUPPORTED)
        authorities = records(runtime.get("identity_authorities", []))
        applications = records(runtime.get("platform_applications", []))
        if authorities or applications:
            result.append((str(address), token(payload.get("node_name", payload.get("name"))), runtime))
    return result


def cloud_only_node_addresses(plan: Mapping[str, Any]) -> frozenset[str]:
    """A cloud declaration with no authored guest or substrate demand needs no VM.

    Keep its native node identity for cloud readback. Any OS, image, hardware,
    topology, guest composition or substrate constraint keeps the ordinary
    workload path; no declared guest effect is discarded by this projection.
    """
    result = set()
    nodes = native_cloud_nodes(plan)
    attached = _attached_workloads(nodes)
    for address, name, _runtime in nodes:
        payload = plan["resources"][address]["payload"]
        if (
            f"nodes.{name}" not in attached
            and not _has_guest_shape(payload)
            and not _has_guest_relations(plan, address)
        ):
            result.add(address)
    return frozenset(result)


def _attached_workloads(nodes: list[tuple[str, str, dict[str, Any]]]) -> set[str]:
    """An explicit attached identity keeps its workload on the guest path."""
    return {
        use.get("workload_ref")
        for _address, _name, runtime in nodes
        for authority in runtime.get("identity_authorities", [])
        for use in authority.get("identity_uses", [])
        if use.get("mode") == "attached"
    }


def _has_guest_shape(payload: dict[str, Any]) -> bool:
    """OS, hardware, topology and infrastructure declarations must retain a guest."""
    spec = payload["spec"]
    return (
        any(
            payload.get(key)
            for key in (
                "os_family",
                "os_distribution",
                "os_version",
                "architecture",
                "network_namespace_target",
                "domain_topology",
            )
        )
        or payload.get("count") not in (None, 1)
        or bool(spec.get("infrastructure"))
        or any(value for key, value in spec["node"].items() if key not in {"type", "description", "runtime"})
    )


def _has_guest_relations(plan: Mapping[str, Any], address: str) -> bool:
    """Keep substrate constraints and target placements on their original guest."""
    return any(
        row.get("address") == address and (row.get("posture") != "open" or row.get("value_domain") is not None)
        for row in plan.get("realization_constraints", [])
    ) or any(
        row.get("payload", {}).get("target_address") == address
        for row in plan["resources"].values()
        if row.get("resource_type") != "node"
    )
