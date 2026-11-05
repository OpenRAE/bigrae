"""Ephemeral provider arguments and strict native-value readers, without RAES imports."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from shared.gcp_range_projects import GcpProjectLease

UNSUPPORTED = "Native cloud declaration is unsupported or unresolved"


@dataclass
class GcpProjectWork:
    """Provider arguments for one exclusively held project."""

    lease: GcpProjectLease
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)
    grants: list[dict[str, Any]] = field(default_factory=list)
    audits: list[dict[str, Any]] = field(default_factory=list)
    attachments: dict[str, str] = field(default_factory=dict)


def records(value: object) -> list[dict[str, Any]]:
    """Malformed presence never becomes an empty declaration."""
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(UNSUPPORTED)
    return value


def supported(row: Mapping[str, Any], fields: set[str], defaults: Mapping[str, Any] | None = None) -> None:
    """Refuse unsupported authored values, including unknown future fields."""
    defaults = defaults or {}
    for key, value in row.items():
        if key not in fields and (key not in defaults or value != defaults[key]):
            raise ValueError(UNSUPPORTED)


def token(value: object, pattern: str = r"[A-Za-z0-9_.-]{1,256}") -> str:
    """Validate concrete provider or native identity without changing its spelling."""
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(UNSUPPORTED)
    return value


SubjectMap = dict[str, tuple[dict[str, Any], GcpProjectWork | None, str]]
TargetMap = dict[str, tuple[GcpProjectWork, str, str]]
