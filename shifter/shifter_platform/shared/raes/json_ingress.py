"""Public shared.raes facade for the pinned RAES bounded JSON parser."""

from raes_contracts.json_ingress import JSONValue, StrictJsonIngressError
from raes_contracts.json_ingress import parse_bounded_json_object as _parse_bounded_json_object


def parse_bounded_json_object(source: str | bytes | bytearray, *, max_bytes: int) -> dict[str, JSONValue]:
    """Parse one bounded JSON object, or raise ValueError for ambiguous input.

    RAES reports a failed ingress check as its own input error. Callers of this
    facade handle invalid input as ValueError, so the facade converts the error.
    """
    try:
        return _parse_bounded_json_object(source, max_bytes=max_bytes)
    except StrictJsonIngressError as exc:
        raise ValueError(str(exc)) from exc


__all__ = ["parse_bounded_json_object"]
