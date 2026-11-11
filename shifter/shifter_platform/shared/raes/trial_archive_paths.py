"""Path containment and the shared error contract for sealed trial archives."""

from shared.exceptions import ValidationError


class TrialArchiveError(ValidationError):
    """Archive bytes cannot support a collection receipt."""


def safe_archive_path(value: object) -> str:
    """Reject aliases before using a name as an inventory key."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise TrialArchiveError("Unsafe archive path")
    return value
