"""Run a fresh trial for a failed experiment entry under the experiment's replacement policy.

A collected, cleaned-up entry whose trial failed gets a new attempt row that
names the attempt it replaces. The row keeps the admitted entry and run
identity; dispatch claims it and creates a new worker. The experiment's RAES
``replacement_policy`` bounds the number of fresh trials per entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

from cms.models import ExperimentEntry

from ._experiment_authority import _audit, _authorize, _fence

if TYPE_CHECKING:
    from shared.credentials import CredentialContext


def _allowed(inputs: dict[str, Any], ordinal: int) -> bool:
    """Return whether the admitted policy authorizes fresh trial number ``ordinal`` for a failed trial."""
    policy = inputs["plan"].get("replacement_policy") or {}
    return "failed" in policy.get("replace_on", []) and ordinal <= policy.get("max_replacements", 0)


def rerun_failed_entry(
    credential: CredentialContext, organization_uuid: UUID, inputs: dict[str, Any], row: ExperimentEntry
) -> str:
    """Record a fresh trial for a failed, cleaned-up entry, or report why none applies."""
    ordinal = (row.replacement_ordinal or 0) + 1
    if row.state != "failed" or not _allowed(inputs, ordinal):
        return "none"
    admission = _authorize(credential, organization_uuid, "manage_content")
    with transaction.atomic():
        _fence(admission)
        if ExperimentEntry.objects.select_for_update().filter(replaces=row).exists():
            return "replaced"
        fresh = ExperimentEntry.objects.create(
            batch_id=row.batch_id,
            organization_uuid=organization_uuid,
            plan_entry_id=row.plan_entry_id,
            run_id=row.run_id,
            replaces=row,
            replacement_ordinal=ordinal,
        )
        _audit(admission, fresh.id, "experiment-rerun-recorded")
    return "rerun-recorded"
