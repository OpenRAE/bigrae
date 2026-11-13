"""Reach an existing disposable worker over its private management SSH.

The worker's original RAES provision input rebuilds its range-cell plan, as
teardown does. Compute Engine readback supplies the pinned host key; the
deterministic RAES secret supplies the management key. Engine never sees either.
"""

from __future__ import annotations

from typing import Any

from shared.worker_trial import WorkerTrialInput

from config import load_gce_range_cell_config
from executors.factory import GuestExecutionContext, build_guest_execution_context
from gcp_range_cell_clients import _build_clients
from gcp_range_cell_host_binding import _host_public_key_from_instance
from gcp_range_cell_ops import _get_or_none
from provisioner_db_operation_input import get_raes_operation_input
from raes_gce_image import registry_image_resolver
from raes_gcp_network_allocation import allocated_networks_for_destroy
from raes_gcp_plan import RaesGcePlanOptions, build_raes_range_cell_plan
from raes_gcp_secret_ops import _default_secret_ops
from raes_range_cloud import prepare_cloud_plan
from raes_range_contract import _require_gce_live_fire_binding
from raes_range_ops import _config_for_range_placement


def trial_instance(instances: list[dict[str, Any]], trial_host: str) -> dict[str, Any]:
    """Return the VM that runs the trial: the one a multi-VM worker names, or a one-VM worker's only VM."""
    selected = [item for item in instances if not trial_host or item["uuid"] == f"{trial_host}#0"]
    if len(selected) != 1:
        raise ValueError("the worker trial host is not exactly one VM")
    return selected[0]


def worker_instance_output(value: WorkerTrialInput) -> dict[str, Any]:
    """Rebuild the trial host VM's management output from retained inputs."""
    request_id = str(value.range_request_id)
    run = get_raes_operation_input(str(value.provision_operation_id), request_id=request_id, operation="provision")
    operation_input = run.input
    raes_plan, _cloud = prepare_cloud_plan(run, run, cleanup_only=True)
    config = _config_for_range_placement(
        request_id, load_gce_range_cell_config(backend=_require_gce_live_fire_binding(operation_input))
    )
    allocation = allocated_networks_for_destroy(request_id, run.operation_id, raes_plan, config)
    plan = build_raes_range_cell_plan(
        request_id,
        operation_input.legacy_range_id,
        raes_plan,
        registry_image_resolver(operation_input),
        RaesGcePlanOptions(
            config=config,
            allocated_network_cidrs=allocation.network_cidrs or None,
            reconstruct_for_teardown=allocation.required and not allocation.network_cidrs,
        ),
    )
    instance = trial_instance(plan["instances"], value.trial_host)
    clients = _build_clients()
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=instance["resource_name"],
    )
    if existing is None:
        raise ValueError("the worker VM is absent")
    secret_ref, _public_key = _default_secret_ops().ensure_ssh(plan["range_id"], instance["uuid"])
    return {
        "uuid": instance["uuid"],
        "asset_type": "gce_vm",
        "os": "linux",
        "private_ip": instance["private_ip"],
        "gcp_zone": plan["zone"],
        "gcp_instance_name": instance["resource_name"],
        "gcp_host_ssh_key_secret_ref": secret_ref,
        "gcp_host_public_key": _host_public_key_from_instance(existing),
        "gcp_host_ssh_username": instance["host_ssh_username"],
        "gcp_host_ssh_port": instance["ssh_port"],
    }


def worker_guest(value: WorkerTrialInput) -> GuestExecutionContext:
    """Return the guest execution context for the trial host VM."""
    return build_guest_execution_context(worker_instance_output(value), os_type="linux", role="raes-node")
