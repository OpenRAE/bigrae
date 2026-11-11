"""Bounded JSON object parser for closed, credential-bearing management APIs."""

from typing import IO

from rest_framework.exceptions import ParseError
from rest_framework.parsers import BaseParser

from shared.raes.json_ingress import parse_bounded_json_object

MAX_JSON_DEPTH = 32


class ClosedJSONParser(BaseParser):
    """Reject duplicate members before serializer validation can lose them."""

    media_type = "application/json"
    max_bytes = 65_536

    def parse(
        self, stream: IO[bytes], media_type: str | None = None, parser_context: dict[str, object] | None = None
    ) -> dict[str, object]:
        try:
            return parse_bounded_json_object(
                stream.read(self.max_bytes + 1), max_bytes=self.max_bytes, max_depth=MAX_JSON_DEPTH
            )
        except ValueError:
            raise ParseError("Invalid JSON object") from None


class ConfigurationJSONParser(ClosedJSONParser):
    """Bound launch/event configuration while preserving duplicate-key checks."""

    max_bytes = 1_000_000
