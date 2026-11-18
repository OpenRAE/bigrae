"""Admit the shared OpenVPN pool to an RAES range's participant target (ADR-039-R10, #2480).

The pool servers live in the shared range VPC. A range that holds an OpenVPN
capability gets one ingress rule: the pool's source networks may reach the
target node, and only on that node's declared participant channels. No other
range host admits the pool, so a domain controller or a second guest is
unreachable from the pool at the cloud layer whatever the servers do.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from gcp_range_cell_firewall import PARTICIPANT_CHANNEL_PORTS
from gcp_range_cell_naming import _short_resource_name
from gcp_range_cell_types import FirewallPlan, InstancePlan
from raes_gcp_firewall import node_tag
from raes_gcp_plan_errors import RaesGcePlanError

__all__ = ["RaesGceVpnAccess", "vpn_pool_firewall_name", "vpn_pool_firewalls"]

_VPN_POOL_PRIORITY = 900


@dataclass(frozen=True, init=False)
class RaesGceVpnAccess:
    """The range's OpenVPN target members and the pool's source networks.

    Destroy and inventory reconstruct the rule name only and leave
    ``pool_cidrs`` empty; such a plan is never used to create the rule.
    """

    target_refs: tuple[str, ...]
    pool_cidrs: tuple[str, ...] = ()

    def __init__(
        self,
        target_ref: str | None = None,
        pool_cidrs: tuple[str, ...] = (),
        *,
        target_refs: tuple[str, ...] | None = None,
    ) -> None:
        """Normalize legacy and multi-target callers into one closed collection."""
        if (target_ref is None) == (target_refs is None):
            raise ValueError("provide exactly one of target_ref or target_refs")
        targets = (target_ref,) if target_ref is not None else tuple(target_refs or ())
        if not targets or targets != tuple(sorted(set(targets))):
            raise ValueError("OpenVPN targets must be non-empty, sorted and unique")
        object.__setattr__(self, "target_refs", targets)
        object.__setattr__(self, "pool_cidrs", tuple(pool_cidrs))

    @property
    def target_ref(self) -> str:
        """Return the sole target for backward-compatible single-target callers."""
        if len(self.target_refs) != 1:
            raise ValueError("OpenVPN access does not identify exactly one target")
        return self.target_refs[0]

    def names_only(self) -> RaesGceVpnAccess:
        """Return the input teardown needs: the rule name, never a creatable rule."""
        return RaesGceVpnAccess(target_refs=self.target_refs)


def vpn_pool_firewall_name(range_id: int, target_ref: str | None = None) -> str:
    """Return a deterministic pool-rule name, preserving the legacy single rule."""
    suffix = hashlib.sha256(target_ref.encode()).hexdigest()[:8] if target_ref is not None else None
    return _short_resource_name("shifter-r", range_id, "vpn-pool", suffix)


def vpn_pool_firewalls(
    range_id: int,
    instance_plans: list[InstancePlan],
    access: RaesGceVpnAccess | None,
) -> list[FirewallPlan]:
    """Return one exact pool ingress rule per authorized target."""
    if access is None:
        return []
    realizing = bool(access.pool_cidrs)
    firewalls: list[FirewallPlan] = []
    for target_ref in access.target_refs:
        target = next((instance for instance in instance_plans if instance["uuid"] == target_ref), None)
        channels = target.get("participant_access_channels", []) if target is not None else []
        ports = sorted({PARTICIPANT_CHANNEL_PORTS[channel] for channel in channels}, key=int)
        if realizing and (target is None or not ports):
            raise RaesGcePlanError("an OpenVPN target declares no participant channel the pool can reach")
        firewalls.append(
            {
                "name": vpn_pool_firewall_name(range_id, target_ref if len(access.target_refs) > 1 else None),
                "direction": "INGRESS",
                "priority": _VPN_POOL_PRIORITY,
                "target_tags": [node_tag(range_id, target_ref.rsplit("#", 1)[0])],
                "source_ranges": list(access.pool_cidrs),
                "allowed": [{"IPProtocol": "tcp", "ports": ports or list(PARTICIPANT_CHANNEL_PORTS.values())}],
            }
        )
    return firewalls
