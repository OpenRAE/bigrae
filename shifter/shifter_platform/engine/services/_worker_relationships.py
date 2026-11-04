"""Durable publication of a worker's SQL-owned native range ancestry."""

from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from shared.authorization import HierarchyRelationshipChange
from shared.authorization.port import configured_authorization_provider

if TYPE_CHECKING:
    from ._range_authority import RangeAuthorityProjection


def publish_worker_relationships(worker_id: UUID) -> None:
    """Use the existing relationship port and primary readback before VM dispatch.

    As for event publication, a lost acknowledgement is recovered by readback.
    Store/model and immutable SQL custody fence every retry. There is no caller
    permission derived from the experiment reference or from a local fallback.
    """
    from engine.models import DisposableWorker

    from ._range_authority import project_range_authority
    from ._worker_retirement import _lock_worker

    try:
        provider = configured_authorization_provider()
        store_id, model_id = str(provider.store_id), str(provider.model_id)
        if not store_id or not model_id:
            raise ValueError("Provider binding unavailable")
        with transaction.atomic():
            worker = _lock_worker(worker_id)
            if worker.authorization_provider_store_id and (
                worker.authorization_provider_store_id,
                worker.authorization_model_id,
            ) != (store_id, model_id):
                raise ValueError("Provider binding changed")
            if worker.authorization_publication_state == "confirmed":
                return
            if worker.retirement_at is not None or worker.terminal_at is not None:
                raise ValueError("Worker already retiring")
            snapshot = project_range_authority(worker.request_id)
            change = HierarchyRelationshipChange(
                f"{snapshot.parent.type}:{snapshot.parent.uuid}", snapshot.parent.type, f"range:{worker.pk}"
            )
            worker.authorization_provider_store_id = store_id
            worker.authorization_model_id = model_id
            worker.authorization_publication_state = "requested"
            worker.save(
                update_fields=[
                    "authorization_provider_store_id",
                    "authorization_model_id",
                    "authorization_publication_state",
                ]
            )
        with suppress(Exception):
            provider.write_relationships(change)
        if not provider.read_relationships(change).grant_present:
            raise ValueError("Primary readback unavailable")
        _confirm_publication(worker_id, snapshot, store_id, model_id)
    except Exception:  # noqa: BLE001  # exact intent and bounded recovery survive an unknown provider outcome
        DisposableWorker.objects.filter(pk=worker_id).exclude(authorization_publication_state="confirmed").update(
            authorization_publication_state="unresolved"
        )
        raise ValueError("Worker authority publication is unavailable") from None


def _confirm_publication(worker_id: UUID, snapshot: RangeAuthorityProjection, store_id: str, model_id: str) -> None:
    """Commit primary readback only while original SQL custody and provider pins agree."""
    from ._range_authority import project_range_authority
    from ._worker_retirement import _lock_worker

    with transaction.atomic():
        worker = _lock_worker(worker_id)
        if project_range_authority(worker.request_id) != snapshot or (
            worker.authorization_provider_store_id,
            worker.authorization_model_id,
        ) != (store_id, model_id):
            raise ValueError("Worker binding changed")
        worker.authorization_publication_state = "confirmed"
        worker.save(update_fields=["authorization_publication_state"])
