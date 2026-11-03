"""Invocation-only confidentiality for preparation results before worker stdout."""

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = b"sealed:fernet:v1:"
_LIMIT = 1_048_576


def seal_result(raw: str, secret: str) -> bytes:
    """Encrypt before stdout; callers provide only their invocation's key."""
    try:
        encrypted = _PREFIX + Fernet(secret.encode("ascii")).encrypt(raw.encode("utf-8"))
        if len(encrypted) > _LIMIT:
            raise ValueError("Preparation output exceeds its bound")
        return encrypted
    except (ValueError, UnicodeError):
        raise ValueError("Preparation output is unavailable") from None


def open_result(raw: str | bytes, secret: str) -> bytes:
    """Refuse cleartext, changed material, another key or oversized output."""
    try:
        encoded = raw.encode("ascii") if isinstance(raw, str) else raw
        if len(encoded) > _LIMIT or not encoded.startswith(_PREFIX):
            raise ValueError("Invalid preparation output")
        return Fernet(secret.encode("ascii")).decrypt(encoded[len(_PREFIX) :].removesuffix(b"\n"))
    except (InvalidToken, ValueError, UnicodeError):
        raise ValueError("Preparation output is unavailable") from None
