"""Range authority, custody, ownership, placement, relationships and request-addressed lifecycle.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .authority import RangeAuthorityProjection as RangeAuthorityProjection
from .authority import has_range_runtime as has_range_runtime
from .authority import lock_range_remote_authority as lock_range_remote_authority
from .authority import native_range_id_by_request as native_range_id_by_request
from .authority import project_range_authority as project_range_authority
from .by_request import RangeOwnershipTransferBlocked as RangeOwnershipTransferBlocked
from .by_request import RangeProjectionIntegrityError as RangeProjectionIntegrityError
from .by_request import RangeWorkspaceRebindOutcome as RangeWorkspaceRebindOutcome
from .by_request import cancel_range_by_request as cancel_range_by_request
from .by_request import destroy_range_by_request as destroy_range_by_request
from .by_request import get_pinned_range_egress_mode_by_request as get_pinned_range_egress_mode_by_request
from .by_request import get_range_failure_reason_by_request as get_range_failure_reason_by_request
from .by_request import range_owner_reassignment_available_by_request as range_owner_reassignment_available_by_request
from .by_request import reassign_range_owner_by_request as reassign_range_owner_by_request
from .by_request import rebind_range_workspace_by_request as rebind_range_workspace_by_request
from .cleanup_retry import reconcile_range_cleanup_verification as reconcile_range_cleanup_verification
from .compatibility import cancel_range as cancel_range
from .compatibility import destroy_range as destroy_range
from .compatibility import get_instance_ips_by_uuid as get_instance_ips_by_uuid
from .compatibility import get_range_pause_resume_capability as get_range_pause_resume_capability
from .compatibility import get_range_status as get_range_status
from .escape import GuestProbeError as GuestProbeError
from .escape import GuestProbeRequest as GuestProbeRequest
from .escape import RangeMembership as RangeMembership
from .escape import get_range_membership as get_range_membership
from .escape import run_guest_probe as run_guest_probe
from .ownership import RangeOwnershipProjection as RangeOwnershipProjection
from .ownership import range_ownership_projection as range_ownership_projection
from .relationships import publish_range_relationships as publish_range_relationships

__all__ = [
    "GuestProbeError",
    "GuestProbeRequest",
    "RangeAuthorityProjection",
    "RangeMembership",
    "RangeOwnershipProjection",
    "RangeOwnershipTransferBlocked",
    "RangeProjectionIntegrityError",
    "RangeWorkspaceRebindOutcome",
    "cancel_range",
    "cancel_range_by_request",
    "destroy_range",
    "destroy_range_by_request",
    "get_instance_ips_by_uuid",
    "get_pinned_range_egress_mode_by_request",
    "get_range_failure_reason_by_request",
    "get_range_membership",
    "get_range_pause_resume_capability",
    "get_range_status",
    "has_range_runtime",
    "lock_range_remote_authority",
    "native_range_id_by_request",
    "project_range_authority",
    "publish_range_relationships",
    "range_owner_reassignment_available_by_request",
    "range_ownership_projection",
    "reassign_range_owner_by_request",
    "rebind_range_workspace_by_request",
    "reconcile_range_cleanup_verification",
    "run_guest_probe",
]
