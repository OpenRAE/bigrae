"""Read dedicated zonal VM/disk identities without fetching provider-supplied URLs."""

from __future__ import annotations

import logging
import re
from time import monotonic
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from shared.native_power import (
    MAX_NATIVE_POWER_DISKS,
    MAX_NATIVE_POWER_FOOTPRINT_DISKS,
    GcePowerIncarnation,
    GcePowerTarget,
    parse_gce_power_incarnation,
    parse_gce_power_target,
    parse_gce_resource_identity,
)

from gce_range_cell_power import _field, _instance_status, _observed_sequence, _persistent_footprint

if TYPE_CHECKING:
    from gcp_range_cell_clients import GCEClients

logger = logging.getLogger(__name__)
_COMPUTE_HOSTS = frozenset({"www.googleapis.com", "compute.googleapis.com"})
_OBSERVATION_BUDGET_SECONDS = 30.0


def _read_timeout(deadline: float) -> float:
    """Bound each SDK read and the complete optional qualification attempt."""
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Native power observation budget exhausted")
    return min(10.0, remaining)


def _resource_name(value: object, target: GcePowerTarget, collection: str) -> str:
    """Interpret only a fixed local Compute reference; never make URL requests."""
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise RuntimeError("Native power resource reference is invalid")
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment:
        raise RuntimeError("Native power resource reference is invalid")
    relative = value
    if parsed.scheme:
        if (
            parsed.scheme != "https"
            or parsed.netloc not in _COMPUTE_HOSTS
            or not parsed.path.startswith("/compute/v1/")
        ):
            raise RuntimeError("Native power resource reference is unsupported")
        relative = parsed.path.removeprefix("/compute/v1/")
    prefix = f"projects/{target.project_id}/zones/{target.zone}/{collection}/"
    if not relative.startswith(prefix):
        raise RuntimeError("Native power resource is outside the dedicated zonal footprint")
    name = relative.removeprefix(prefix)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", name):
        raise RuntimeError("Native power resource name is invalid")
    return name


def observe_power_incarnation(
    target: GcePowerTarget,
    *,
    clients: GCEClients,
    deadline: float | None = None,
    required_status: str | None = None,
) -> GcePowerIncarnation:
    """Observe VM and disk identities, exclusive attachments and stable membership."""
    disks_client = clients.disks
    if disks_client is None:
        raise RuntimeError("Native power disk observation is unavailable")
    deadline = (
        min(deadline, monotonic() + _OBSERVATION_BUDGET_SECONDS)
        if deadline is not None
        else monotonic() + _OBSERVATION_BUDGET_SECONDS
    )
    before = clients.instances.get(
        project=target.project_id,
        zone=target.zone,
        instance=target.instance_name,
        timeout=_read_timeout(deadline),
        retry=None,
    )
    identity, sources = _persistent_footprint(before)
    if len(sources) > MAX_NATIVE_POWER_DISKS:
        raise RuntimeError("Native power disk footprint is too large")
    disks = []
    for source in sources:
        name = _resource_name(source, target, "disks")
        disk = disks_client.get(
            project=target.project_id,
            zone=target.zone,
            disk=name,
            timeout=_read_timeout(deadline),
            retry=None,
        )
        users = _observed_sequence(_field(disk, "users"))
        if len(users) != 1 or _resource_name(users[0], target, "instances") != target.instance_name:
            raise RuntimeError("Native power disk is shared or unobserved")
        disks.append({"name": name, "identity": parse_gce_resource_identity(_field(disk, "id"))})
    after = clients.instances.get(
        project=target.project_id,
        zone=target.zone,
        instance=target.instance_name,
        timeout=_read_timeout(deadline),
        retry=None,
    )
    if _persistent_footprint(after) != (identity, sources):
        raise RuntimeError("Native power footprint changed during observation")
    if required_status is not None and any(_instance_status(vm) != required_status for vm in (before, after)):
        raise RuntimeError("Native power resource state changed during observation")
    return parse_gce_power_incarnation({"instance_identity": identity, "disks": disks})


def retain_power_incarnations(instances: list[dict[str, Any]], *, clients: GCEClients) -> None:
    """Optionally qualify the entire provisioned footprint, with no partial claims.

    A provisioning-only launch may lack power capability. The power-input
    builder refuses missing qualification and never reconstructs it later.
    """
    for instance in instances:
        instance.pop("native_power_incarnation", None)
    qualified = []
    disk_count = 0
    deadline = monotonic() + _OBSERVATION_BUDGET_SECONDS
    try:
        for instance in instances:
            if instance.get("bootstrap_capability") != "standard":
                return
            target = parse_gce_power_target(
                {
                    "backend": "gce",
                    "project_id": instance.get("gcp_project_id"),
                    "zone": instance.get("gcp_zone"),
                    "instance_name": instance.get("gcp_instance_name"),
                    "bootstrap_capability": "standard",
                },
                instance_id=instance.get("instance_id", ""),
            )
            incarnation = observe_power_incarnation(target, clients=clients, deadline=deadline)
            disk_count += len(incarnation.disks)
            if disk_count > MAX_NATIVE_POWER_FOOTPRINT_DISKS:
                return
            qualified.append(incarnation)
    except Exception as exc:  # noqa: BLE001  # optional qualification; only the fault class leaves this boundary
        logger.warning("Native power qualification unavailable exc_type=%s", type(exc).__name__)
        return
    for instance, incarnation in zip(instances, qualified, strict=True):
        instance["native_power_incarnation"] = incarnation.to_transport()
