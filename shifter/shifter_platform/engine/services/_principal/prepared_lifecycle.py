"""Prepared range lifecycle facts passed between owning-service steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from shared.credentials import CredentialContext


@dataclass(frozen=True, slots=True)
class PreparedRangeLifecycle:
    """In-process owning-service facts; never an HTTP or worker credential."""

    request_id: UUID
    operation: str
    native_id: int
    status: str
    authority: tuple[tuple[str, object], ...]
    credential: CredentialContext
