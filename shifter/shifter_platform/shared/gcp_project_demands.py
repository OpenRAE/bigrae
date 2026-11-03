"""Process-local project custody demands from native node runtime payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import TypeAdapter

from shared.gcp_range_projects import ProjectID, ProjectNumber

_UNSUPPORTED = "Registered project scope is unsupported"
MAX_PROJECT_SCOPE_REFERENCES = 64


@dataclass(frozen=True, slots=True)
class GcpProjectDemand:
    """Provider identity selection, not another authored intent or permission grant."""

    scope_ref: str
    project_id: str
    project_number: str


def node_gcp_project_demands(node_name: str, runtime: object) -> tuple[GcpProjectDemand, ...]:
    """Read explicit GCP project scopes without inventing provider IDs or defaults.

    Callers first validate the native plan and producer version. This reads
    custody identities only; supported-effect admission still owns every other
    native field and must finish before the first provider mutation.
    """
    if runtime is None:
        return ()
    if not isinstance(runtime, Mapping):
        raise ValueError(_UNSUPPORTED)
    rows = _records(runtime.get("identity_authorities", []))
    result: list[GcpProjectDemand] = []
    seen: set[str] = set()
    for authority in rows:
        scopes = _records(authority.get("resource_scopes", []))
        if not scopes:
            continue
        node_name = _identifier(node_name)
        if authority.get("kind") != "cloud_iam":
            raise ValueError(_UNSUPPORTED)
        authority_id = _identifier(authority.get("identity_authority_id"))
        for scope in scopes:
            if scope.get("provider") != "gcp" or scope.get("scope_kind") != "project":
                raise ValueError(_UNSUPPORTED)
            scope_id = _identifier(scope.get("scope_id"))
            reference = f"nodes.{node_name}.runtime.identity_authorities.{authority_id}.resource_scopes.{scope_id}"
            if reference in seen or len(reference) > 1024 or len(result) >= MAX_PROJECT_SCOPE_REFERENCES:
                raise ValueError(_UNSUPPORTED)
            seen.add(reference)
            try:
                project_id = TypeAdapter(ProjectID).validate_python(scope.get("native_id"))
                incarnation = scope.get("incarnation_id", "")
                number = "" if incarnation == "" else TypeAdapter(ProjectNumber).validate_python(incarnation)
            except ValueError:
                raise ValueError(_UNSUPPORTED) from None
            result.append(GcpProjectDemand(reference, project_id, number))
    return tuple(result)


def _identifier(value: object) -> str:
    """Retain exact native symbols; no substring replacement or name-based policy."""
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ValueError(_UNSUPPORTED)
    return value


def _records(value: object) -> list[Mapping[str, object]]:
    """Malformed presence cannot become an empty scope selection."""
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(_UNSUPPORTED)
    return value
