"""Canonical private bootstrap identity facts shared by trusted operator commands."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.private_files import read_private_file
from shared.raes.json_ingress import parse_bounded_json_object

_MAX_FACTS_BYTES = 65536


class IdentityBootstrapFacts(BaseModel):
    """Exact immutable provider identity selected for the one-time first grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["shifter.identity-bootstrap-facts/v1"] = Field(alias="schema")
    issuer: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)


def load_identity_bootstrap_facts(path_value: str) -> IdentityBootstrapFacts:
    """Load one owner-only bootstrap selection without accepting email lookup."""
    path = Path(path_value)
    try:
        payload = parse_bounded_json_object(
            read_private_file(path, limit=_MAX_FACTS_BYTES), max_bytes=_MAX_FACTS_BYTES, max_depth=32
        )
        facts = IdentityBootstrapFacts.model_validate(payload)
    except (OSError, ValueError, ValidationError) as exc:
        raise ValueError("bootstrap facts document is invalid") from exc
    if facts.issuer != facts.issuer.strip() or facts.subject != facts.subject.strip():
        raise ValueError("bootstrap facts document is invalid")
    return facts
