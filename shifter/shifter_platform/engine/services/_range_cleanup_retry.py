"""Retry unverified native teardown through the incumbent destroy workflow."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from engine.models import OperationResultInbox, ProvisionerLaunchIntent, Range


def retry_range_cleanup_verification(request_id: UUID, *, now: datetime) -> bool:
    """Queue a new exact-custody destroy only after a terminal unknown outcome.

    Attempts retain their immutable outbox/input/results. Delay starts at result
    application, doubles from 60 seconds, and caps at one hour. The obligation
    never expires merely because inventory is unavailable.
    """
    from engine.models import Range

    from ._principal_lifecycle import _commit_destroy, prepare_system_range_cleanup

    with transaction.atomic():
        row = (
            Range.objects.select_for_update(of=("self",))
            .select_related("request")
            .filter(request__request_id=request_id, status="destroyed", owner_principal_uuid__isnull=False)
            .first()
        )
        if (
            row is None
            or row.cms_range_uuid is None
            or row.resource_generation is None
            or row.provisioner_operation_id is None
        ):
            return False
        evidence = _retryable_cleanup_evidence(request_id, row.provisioner_operation_id, row.cms_range_uuid, row.pk)
        if evidence is None:
            return False
        intent, terminal = evidence
        return _cleanup_retry_due(row, intent, terminal, now) and _commit_destroy(
            prepare_system_range_cleanup(request_id), _verification_retry=True
        )


def _retryable_cleanup_evidence(
    request_id: UUID, operation_id: UUID, cms_range_uuid: UUID, native_id: int
) -> tuple[ProvisionerLaunchIntent, OperationResultInbox] | None:
    """Read only the current accepted destroy and its applied terminal observation under the target lock."""
    from engine.models import OperationResultInbox, ProvisionerLaunchIntent
    from shared.operation_results import ResultStep

    from ._cleanup_verification import is_range_generation_cleanup_verified_absent

    intent = ProvisionerLaunchIntent.objects.select_for_update().filter(operation_id=operation_id).first()
    if intent is None or intent.payload.get("operation") != "destroy":
        return None
    terminal = (
        OperationResultInbox.objects.filter(
            operation_id=intent.operation_id,
            request_id=request_id,
            operation="destroy",
            result_step=ResultStep.RAES_TERMINAL_DESTROYED,
            disposition="APPLIED",
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if terminal is None or is_range_generation_cleanup_verified_absent(request_id, cms_range_uuid, native_id):
        return None
    return intent, terminal


def _cleanup_retry_due(
    row: Range, intent: ProvisionerLaunchIntent, terminal: OperationResultInbox, now: datetime
) -> bool:
    """Bound retry cadence by exact current custody and the immutable applied observation time."""
    from engine.models import ProvisionerLaunchIntent

    attempts = ProvisionerLaunchIntent.objects.filter(
        authority_resource_uuid=row.cms_range_uuid,
        authority_binding_digest=intent.authority_binding_digest,
        payload__operation="destroy",
    ).count()
    delay = min(60 * 2 ** min(max(attempts - 1, 0), 6), 3600)
    return (terminal.applied_at or terminal.created_at) + timedelta(seconds=delay) <= now


def reconcile_range_cleanup_verification(*, now: datetime | None = None, limit: int = 100) -> int:
    """Retry only current unverified ordinary native destroys in a bounded pass."""
    from django.db.models import OuterRef, Subquery
    from django.utils import timezone

    from engine.models import CleanupVerificationOutcome, Range, RangeCleanupVerification

    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Cleanup reconciliation limit is invalid")
    moment = now or timezone.now()
    latest = (
        RangeCleanupVerification.objects.filter(
            request_id=OuterRef("request__request_id"), operation_id=OuterRef("provisioner_operation_id")
        )
        .order_by("-created_at", "-pk")
        .values("outcome")[:1]
    )
    requests = list(
        Range.objects.filter(
            status="destroyed",
            cms_range_uuid__isnull=False,
            owner_principal_uuid__isnull=False,
            resource_generation__isnull=False,
            provisioner_operation_id__isnull=False,
            warm_generation__isnull=True,
            disposable_worker__isnull=True,
        )
        .annotate(cleanup_outcome=Subquery(latest))
        .filter(cleanup_outcome__in=[CleanupVerificationOutcome.INCOMPLETE, CleanupVerificationOutcome.RESIDUALS_FOUND])
        .order_by("updated_at", "pk")
        .values_list("request__request_id", flat=True)[:limit]
    )
    queued = 0
    for request_id in requests:
        try:
            queued += int(retry_range_cleanup_verification(UUID(str(request_id)), now=moment))
        except Exception:  # noqa: BLE001  # each obligation remains held; provider diagnostics stay private
            logger.warning("Ordinary range cleanup retry remains pending")
    return queued
