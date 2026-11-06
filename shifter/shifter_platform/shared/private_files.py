"""Bounded reads of operator-owned private inputs without following links."""

import os
import stat
from pathlib import Path


def read_private_file(path: str | Path, *, limit: int) -> bytes:
    """Read one owner-only regular file, checking the opened descriptor."""
    if type(limit) is not int or limit < 1:
        raise ValueError("Private input bound is invalid")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_size > limit
            ):
                raise ValueError
            payload = handle.read(limit + 1)
        if len(payload) > limit:
            raise ValueError
        return payload
    except (OSError, ValueError):
        raise ValueError("Private input is unavailable") from None
