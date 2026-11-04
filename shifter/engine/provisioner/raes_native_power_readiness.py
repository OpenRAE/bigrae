"""Read-only guest qualification after native power restoration."""

from __future__ import annotations

from ipaddress import IPv4Address
from typing import Any

from shared.model_access.network import RFC1918_IPV4_NETWORKS
from shared.raes.operation_input import RaesOperationInput
from shared.raes.power_input import NativePowerInput

from gce_range_cell_incarnation import observe_power_incarnation
from gce_range_cell_power import _field, _instance_status, _observed_sequence
from gcp_guest_secrets import existing_raes_ssh_secret
from gcp_range_cell_clients import GCEClients
from gcp_range_cell_host_binding import _host_public_key_from_instance
from raes_composition_verification import verify_bootstrap_composition
from raes_gce_image import registry_image_resolver
from raes_operating_system import observe_operating_systems, validate_operating_systems
from raes_plan import RaesPlan


def resumed_guest_outputs(
    original: RaesOperationInput,
    plan: RaesPlan,
    power: NativePowerInput,
    clients: GCEClients,
) -> list[dict[str, Any]]:
    """Recover management access from the original policy and exact live VM."""
    resolve = registry_image_resolver(original)
    nodes = {node.address: node for node in plan.nodes}
    outputs = []
    for member in power.members:
        profile = resolve(nodes[member.member_ref.rsplit("#", 1)[0]])
        if profile.bootstrap_capability != "standard":
            raise ValueError("Native power management policy unavailable")
        target = member.target
        vm = clients.instances.get(
            project=target.project_id,
            zone=target.zone,
            instance=target.instance_name,
            timeout=10.0,
            retry=None,
        )
        interfaces = _observed_sequence(_field(vm, "network_interfaces", "networkInterfaces"))
        if _instance_status(vm) != "RUNNING" or len(interfaces) != 1:
            raise ValueError("Native power guest observation unavailable")
        address = IPv4Address(str(_field(interfaces[0], "network_i_p", "networkIP")))
        host_key = _host_public_key_from_instance(vm)
        if not any(address in network for network in RFC1918_IPV4_NETWORKS) or not host_key:
            raise ValueError("Native power management observation unavailable")
        if observe_power_incarnation(target, clients=clients) != member.incarnation:
            raise ValueError("Native power resource incarnation changed")
        outputs.append(
            {
                "uuid": member.member_ref,
                "asset_type": "gce_vm",
                "private_ip": str(address),
                "gcp_host_ssh_username": profile.host_ssh_username or "raes",
                "gcp_host_ssh_port": profile.host_ssh_port,
                "gcp_host_public_key": host_key,
                "gcp_host_ssh_key_secret_ref": existing_raes_ssh_secret(original.legacy_range_id, member.member_ref),
            }
        )
    return outputs


def verify_resumed_guests(
    original: RaesOperationInput,
    plan: RaesPlan,
    power: NativePowerInput,
    clients: GCEClients,
) -> None:
    """Reuse provisioning's authenticated, read-only OS and composition checks."""
    outputs = resumed_guest_outputs(original, plan, power, clients)
    validate_operating_systems(plan, observe_operating_systems(plan, outputs))
    verify_bootstrap_composition(plan, outputs)
    # An observation cannot qualify a replacement made during guest verification.
    for member in power.members:
        if observe_power_incarnation(member.target, clients=clients, required_status="RUNNING") != member.incarnation:
            raise ValueError("Native power resource incarnation changed")
