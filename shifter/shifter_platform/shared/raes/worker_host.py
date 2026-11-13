"""Validate apparatus against the installed RAES provisioning contract."""

from dataclasses import dataclass
from typing import Any

from raes_contracts.planning import ProvisioningPlan

from shared.raes.completion import load_serialized_plan
from shared.raes.runtime_target import interpret_provisioning_plan

#: A worker trial uses a small, fixed set of VMs; more would be a range, not a worker.
MAX_WORKER_VMS = 4


@dataclass(frozen=True, slots=True)
class WorkerNode:
    """One admitted Linux VM of a worker host plan."""

    address: str
    source: str
    version: str
    cpu: int
    ram: int


def worker_host_nodes(value: dict[str, Any]) -> tuple[WorkerNode, ...]:
    """Return the admitted Linux VMs of a worker host plan, in address order, on its one network."""
    plan = _validated_host_plan(value)
    resources = list(plan.resources.values())
    nodes = [item for item in resources if item.resource_type == "node"]
    networks = [item for item in resources if item.resource_type == "network"]
    if not 1 <= len(nodes) <= MAX_WORKER_VMS or len(networks) != 1 or len(resources) != len(nodes) + 1:
        raise ValueError(f"Worker apparatus requires one network and one to {MAX_WORKER_VMS} VMs")
    return tuple(_worker_node(node) for node in sorted(nodes, key=lambda item: item.address))


def _worker_node(node: Any) -> WorkerNode:
    """Validate one planned VM: Linux, a single instance, a pinned source, and bounded size."""
    if node.payload.get("os_family") != "linux" or node.payload.get("count", 1) != 1:
        raise ValueError("Worker apparatus VMs must each be one Linux instance")
    spec = node.payload["spec"]["node"]
    source, size = spec["source"], spec["resources"]
    if not source.get("name") or source.get("version") in (None, "", "*", "latest"):
        raise ValueError("Worker host source must be pinned")
    cpu, ram = size.get("cpu"), size.get("ram")
    _validate_host_size(cpu, ram)
    return WorkerNode(node.address, source["name"], source["version"], cpu, ram)


def _validate_host_size(cpu: object, ram: object) -> None:
    """Refuse ambiguous or unbounded VM resources before profile validation."""
    if type(cpu) is not int or not 1 <= cpu <= 256 or type(ram) is not int or not 128 * 1024**2 <= ram <= 4 * 1024**4:
        raise ValueError("Worker host resources are invalid")


def _validated_host_plan(value: dict[str, Any]) -> ProvisioningPlan:
    """Reuse the pinned RAES parser and realizability checks for apparatus input."""
    plan = load_serialized_plan(value)
    serialized, diagnostics = interpret_provisioning_plan(plan)
    if serialized is None or any(item.is_error for item in diagnostics):
        raise ValueError("Worker host plan is not supported")
    return plan
