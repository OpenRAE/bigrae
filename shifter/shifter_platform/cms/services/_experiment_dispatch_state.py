"""Dispatch stop and attempt deadline state for a retained experiment batch."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from cms.models import ExperimentBatch
from shared.credentials import CredentialContext

from ._experiment_authority import _audit, _authorize, _fence
from ._experiment_batches import _attempt


def stop_experiment_batch(credential: CredentialContext, organization_uuid: UUID, batch_id: UUID) -> None:
    """Persist a dispatch stop once; claims and trial starts check it."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    with transaction.atomic():
        _fence(admission)
        row = ExperimentBatch.objects.select_for_update().get(pk=batch_id, organization_uuid=organization_uuid)
        if row.dispatch_stopped_at is None:
            row.dispatch_stopped_at = timezone.now()
            row.save(update_fields=["dispatch_stopped_at"])
            _audit(admission, row.id, "experiment-dispatch-stopped")


def experiment_dispatch_stopped(organization_uuid: UUID, batch_id: UUID) -> bool:
    """Return True after a stop request for the batch."""
    return ExperimentBatch.objects.filter(
        pk=batch_id, organization_uuid=organization_uuid, dispatch_stopped_at__isnull=False
    ).exists()


def reserve_trial_deadline(
    credential: CredentialContext, organization_uuid: UUID, token: UUID, timeout_seconds: int
) -> datetime:
    """Set the attempt's trial deadline once and return the stored value."""
    admission = _authorize(credential, organization_uuid, "manage_content")
    with transaction.atomic():
        _fence(admission)
        row = _attempt(organization_uuid, token, locked=True)
        if row.trial_deadline is None:
            row.trial_deadline = (timezone.now() + timedelta(seconds=timeout_seconds)).replace(microsecond=0)
            row.save(update_fields=["trial_deadline", "updated_at"])
        return row.trial_deadline
