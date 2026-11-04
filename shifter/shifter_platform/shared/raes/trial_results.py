"""Read-only projections of validated original trial records for an export."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity, VerifiedTrialArchive


@dataclass(frozen=True, slots=True)
class TrialArchiveContents:
    """Derived views; the original portable contracts remain authoritative."""

    facts: VerifiedTrialArchive
    plan: dict[str, Any]
    run: dict[str, Any]
    members: list[dict[str, Any]]
    capture_gaps: list[dict[str, Any]]
    usage: list[dict[str, Any]]


def inspect_trial_archive(path: Path, expected: TrialArchiveIdentity) -> TrialArchiveContents:
    """Reuse custody validation and released RAES contracts without changing bytes."""
    raise TrialArchiveError("Trial archive inspection is not implemented")
