"""Engine participant membership and the shared pinned guest-probe transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.guest_probe import GuestProbeError, GuestProbeRequest, run_guest_probe


@dataclass(frozen=True)
class RangeMembership:
    """Non-secret, platform-owned membership for a provisioned range.

    This is the service-seam value the cms escape-validation resolver consumes so
    it never imports ``engine.models`` directly (ADR-001). ``instances`` are the
    plain provisioner output dicts (private IP, participant/host SSH references,
    role, uuid); no ORM objects cross the boundary.
    """

    range_id: int
    instances: tuple[dict[str, Any], ...]
    subnet_cidrs: tuple[str, ...]


def get_range_membership(request_id: str) -> RangeMembership | None:
    """Return the provisioned membership + subnet CIDRs for a range, or None.

    Operator/management context: reads the persisted range and its subnet
    allocations. Returns plain data so callers in other layers do not import the
    engine models.
    """
    from engine.models import Range, SubnetAllocation

    range_obj = Range.objects.filter(request__request_id=request_id).order_by("-id").first()
    if range_obj is None:
        return None
    instances = tuple(dict(inst) for inst in (range_obj.provisioned_instances or []) if isinstance(inst, dict))
    subnet_cidrs = tuple(
        sorted({row.cidr for row in SubnetAllocation.objects.filter(request_id=request_id) if row.cidr})
    )
    if not subnet_cidrs and range_obj.subnet_cidr:
        subnet_cidrs = (range_obj.subnet_cidr,)
    return RangeMembership(range_id=range_obj.id, instances=instances, subnet_cidrs=subnet_cidrs)


__all__ = ["GuestProbeError", "GuestProbeRequest", "RangeMembership", "get_range_membership", "run_guest_probe"]
