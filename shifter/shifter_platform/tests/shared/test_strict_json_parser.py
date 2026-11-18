"""Closed management APIs reject ambiguous or unbounded JSON before serializer validation."""

import io

import pytest
from rest_framework.exceptions import ParseError

from shared.api.strict_json import MAX_JSON_DEPTH, ClosedJSONParser, ConfigurationJSONParser


def _parse(parser, raw: bytes):
    return parser.parse(io.BytesIO(raw))


def test_closed_parser_returns_a_plain_object():
    assert _parse(ClosedJSONParser(), b'{"name": "range", "count": 2}') == {"name": "range", "count": 2}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"name": "a", "name": "b"}',
        b'{"value": NaN}',
        b'{"value": Infinity}',
        b"[1, 2]",
        b"",
        b"{not json}",
        ("[" * MAX_JSON_DEPTH + "]" * MAX_JSON_DEPTH).join([b'{"v": '.decode(), "}"]).encode(),
    ],
)
def test_closed_parser_rejects_ambiguous_or_deep_input(raw):
    with pytest.raises(ParseError):
        _parse(ClosedJSONParser(), raw)


def test_closed_parser_rejects_bodies_over_its_bound():
    body = b'{"v": "' + b"x" * ClosedJSONParser.max_bytes + b'"}'
    with pytest.raises(ParseError):
        _parse(ClosedJSONParser(), body)
    assert _parse(ConfigurationJSONParser(), body) == {"v": "x" * ClosedJSONParser.max_bytes}
