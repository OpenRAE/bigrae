"""Validate apparatus against the installed RAES provisioning contract."""

from typing import Any

from raes_contracts.planning import ProvisioningPlan

from shared.raes.completion import load_serialized_plan
from shared.raes.runtime_target import interpret_provisioning_plan


def worker_host_shape(value: dict[str, Any]) -> tuple[str, str, str, int, int]:
    """Return one admitted Linux VM's address, source, version, CPU and RAM."""
    plan = _validated_host_plan(value)
    resources = list(plan.resources.values())
    nodes = [item for item in resources if item.resource_type == "node"]
    networks = [item for item in resources if item.resource_type == "network"]
    if len(resources) != 2 or len(nodes) != 1 or len(networks) != 1:
        raise ValueError("Worker apparatus requires one VM and one network")
    node = nodes[0]
    if node.payload.get("os_family") != "linux" or node.payload.get("count", 1) != 1:
        raise ValueError("Worker apparatus requires one Linux VM")
    spec = node.payload["spec"]["node"]
    source, size = spec["source"], spec["resources"]
    if not source.get("name") or source.get("version") in (None, "", "*", "latest"):
        raise ValueError("Worker host source must be pinned")
    cpu, ram = size.get("cpu"), size.get("ram")
    _validate_host_size(cpu, ram)
    return node.address, source["name"], source["version"], cpu, ram


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
