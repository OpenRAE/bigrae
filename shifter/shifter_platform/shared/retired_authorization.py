"""Authorization values retired with the model broker (#2909).

Recorded operation authority is immutable, so stored ceilings and scopes can
still name these values. Readers drop exactly these values when they rebuild a
recorded credential. Any other unknown value still fails closed. Data
migrations use the same values to retire credentials that hold them.
"""

from __future__ import annotations

from collections.abc import Iterable

RETIRED_ACTIONS = frozenset(
    {
        "account.manage_model_sources",
        "installation.manage_model_sources",
        "organization.manage_model_sources",
        "workspace.manage_model_sources",
        "workspace.publish_model_access",
    }
)

RETIRED_SCOPES = frozenset(
    {
        *(f"authorization:{action}" for action in RETIRED_ACTIONS),
        "model-access:operator:read",
        "model-access:operator:write",
        "model-access:sharing:read",
        "model-access:sharing:write",
        "model-access:event:read",
        "model-access:event:write",
        "model-access:range:read",
        "model-access:range:write",
        "model-access:participant:read",
    }
)

_RETIRED = RETIRED_ACTIONS | RETIRED_SCOPES


def without_retired_values(values: frozenset[str]) -> frozenset[str]:
    """Remove retired actions and scopes; this can only narrow a recorded credential."""
    return values - _RETIRED


def without_retired(values: Iterable[str]) -> list[str]:
    """Return the values in their stored order, without retired actions or scopes."""
    return [value for value in values if value not in _RETIRED]


def holds_retired(values: Iterable[str]) -> bool:
    """Return whether any stored value is a retired action or scope."""
    return any(value in _RETIRED for value in values)
