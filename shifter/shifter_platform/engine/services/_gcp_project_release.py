"""Release project custody only after the current native restoration is applied."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from engine.models import GcpRangeProject, GcpRangeProjectUse, OperationInput, Range
from shared.gcp_range_projects import MAX_PROJECTS_PER_RANGE, GcpProjectLease, GcpProjectRestorationProof

if TYPE_CHECKING:
    from engine.models import OperationResultInbox

_UNVERIFIED = "Registered project restoration is unverified"


def project_restoration_uses(
    target: Range, inventory: object
) -> tuple[tuple[GcpRangeProjectUse, GcpProjectRestorationProof], ...]:
    """A global absence claim must include exact positive readback for every held project."""
    uses = tuple(GcpRangeProjectUse.objects.filter(range=target, released_at__isnull=True).order_by("project_id"))
    if not uses:
        return ()
    if not isinstance(inventory, dict) or inventory.get("outcome") != "VERIFIED_ABSENT":
        return ()
    _require_current_destroy(target)
    by_lease = _restoration_proofs(uses, inventory)
    verified = []
    for use in uses:
        lease = GcpProjectLease.model_validate(use.binding)
        proof = by_lease[use.pk]
        if (
            proof.outcome != "restored"
            or proof.registration_id != use.project_id
            or proof.baseline_state_digest != lease.baseline.state_digest
        ):
            raise ValueError(_UNVERIFIED)
        verified.append((use, proof))
    return tuple(verified)


def _require_current_destroy(target: Range) -> None:
    """Only the original range's current native destroy can release its custody."""
    if (
        target.request is None
        or target.provisioner_operation_id is None
        or not OperationInput.objects.filter(
            operation_id=target.provisioner_operation_id,
            request_id=target.request.request_id,
            resource="raes-range",
            operation="destroy",
        ).exists()
    ):
        raise ValueError(_UNVERIFIED)


def _restoration_proofs(
    uses: tuple[GcpRangeProjectUse, ...], inventory: dict[str, Any]
) -> dict[UUID, GcpProjectRestorationProof]:
    """Require bounded positive proof for every held lease and no residual resource."""
    scope = inventory.get("scope")
    proofs = scope.get("gcp_projects") if isinstance(scope, dict) else None
    if (
        inventory.get("residual_categories") != []
        or not isinstance(proofs, list)
        or len(proofs) != len(uses)
        or len(proofs) > MAX_PROJECTS_PER_RANGE
    ):
        raise ValueError(_UNVERIFIED)
    parsed = [GcpProjectRestorationProof.model_validate(proof) for proof in proofs]
    by_lease = {proof.lease_id: proof for proof in parsed}
    if len(by_lease) != len(parsed) or by_lease.keys() != {use.pk for use in uses}:
        raise ValueError(_UNVERIFIED)
    return by_lease


def release_applied_project_restorations(result: OperationResultInbox) -> None:
    """Run after inbox APPLIED is saved, inside its transaction and Range mutex."""
    if result.disposition != "APPLIED" or (result.resource, result.operation, result.result_step) != (
        "raes-range",
        "destroy",
        "raes_terminal_destroyed",
    ):
        return
    if not transaction.get_connection().in_atomic_block:
        raise ValueError(_UNVERIFIED)
    target = Range.objects.select_for_update().get(provisioner_operation_id=result.operation_id)
    verified = project_restoration_uses(target, result.envelope["payload"].get("cleanup_inventory"))
    # Keep allocation and release under the same stable project-row lock order.
    list(
        GcpRangeProject.objects.select_for_update()
        .filter(pk__in=[use.project_id for use, _proof in verified])
        .order_by("pk")
    )
    for use, proof in verified:
        GcpRangeProjectUse.objects.filter(pk=use.pk, released_at__isnull=True).update(
            released_at=timezone.now(),
            release_operation_id=result.operation_id,
            release_state_digest=proof.observed_state_digest,
        )
