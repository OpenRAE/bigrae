"""Replace a failed experiment trial under the experiment's RAES replacement policy.

A collected, cleaned-up entry whose archived run status the policy names gets
one RAES replacement per ordinal, up to the policy limit. The child plan is
committed as a pending entry before dispatch claims it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from cms.models import ExperimentEntry, RaesPackageSource
from cms.scenarios.pack_validation import PackDigestError, verify_pack_digest
from shared.cloud.exceptions import CloudStorageError
from shared.exceptions import CMSError
from shared.raes.experiment_replacement import compile_experiment_replacement, replacement_allowed
from shared.raes.package_loader import RaesPackageError

from ._experiment_batches import _owner_validation, _pack_snapshot, record_experiment_replacement
from ._trial_archives import read_archived_run

if TYPE_CHECKING:
    from shared.credentials import CredentialContext

logger = logging.getLogger(__name__)


def _slot_history(row: ExperimentEntry) -> list[dict[str, Any]]:
    """Return the slot's committed replacement decisions, oldest first."""
    history = []
    current: ExperimentEntry | None = row
    while current is not None and current.replacement_json:
        history.append(json.loads(current.replacement_json))
        current = current.replaces
    return list(reversed(history))


def replace_experiment_entry(
    credential: CredentialContext, organization_uuid: UUID, inputs: dict[str, Any], row: ExperimentEntry
) -> str:
    """Record the next authorized replacement for a finished entry, or report why none applies."""
    ordinal = (row.replacement_ordinal or 0) + 1
    token = row.token
    if token is None or row.receipt is None or not replacement_allowed(inputs, row.receipt.run_status, ordinal):
        return "none"
    if ExperimentEntry.objects.filter(replaces=row).exists():
        return "replaced"
    replacement = _compile_replacement(credential, organization_uuid, inputs, row, row.receipt.pk)
    if replacement is not None:
        record_experiment_replacement(credential, organization_uuid, token, replacement)
    return "replacement-refused" if replacement is None else "replacement-recorded"


def _compile_replacement(
    credential: CredentialContext,
    organization_uuid: UUID,
    inputs: dict[str, Any],
    row: ExperimentEntry,
    receipt_id: UUID,
) -> dict[str, Any] | None:
    """Compile the slot's next RAES replacement, or return None when RAES or the pack refuses it."""
    history = _slot_history(row)
    root_entry_id = history[0]["root_entry_id"] if history else row.plan_entry_id
    source = RaesPackageSource.objects.filter(
        organization_uuid=organization_uuid, package_digest=inputs["source"]["package_digest"]
    ).first()
    try:
        if source is None:
            raise CMSError("The batch's pack is no longer registered")
        failed_run = read_archived_run(credential, organization_uuid, receipt_id)
        with _pack_snapshot(source) as root:
            if not verify_pack_digest(root, source.package_digest):
                raise CMSError("The batch's pack changed")
            return compile_experiment_replacement(
                root,
                inputs,
                root_entry_id=root_entry_id,
                previous=history,
                failed_run=failed_run,
                cleanup_receipt=json.loads(row.cleanup_receipt_json),
                owner_validation=_owner_validation(organization_uuid),
            )
    except (CMSError, ValueError, RaesPackageError, PackDigestError, CloudStorageError, OSError) as exc:
        logger.warning("experiment replacement refused entry=%s reason=%s", row.plan_entry_id, str(exc)[:200])
        return None
