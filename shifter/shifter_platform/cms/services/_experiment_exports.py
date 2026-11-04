"""Organize retained trial results through their existing service owners."""

from uuid import UUID

from shared.credentials import CredentialContext
from shared.exceptions import CMSError

MAX_EXPORT_ENTRIES = 10000
MAX_EXPORT_ARCHIVES = 10000
MAX_EXPORT_BYTES = 128 * 1024**2


def export_experiment_batch(
    credential: CredentialContext, organization_uuid: UUID, batch_id: UUID
) -> dict[str, object]:
    """Publish deterministic manifest and CSV/JSON indexes to approved tenant storage."""
    raise CMSError("Experiment export is not implemented")
