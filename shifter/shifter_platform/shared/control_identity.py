"""Verify Google workload assertions from deployment-configured controllers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from google.auth.transport import Response


class GoogleRequest(Protocol):
    """Bounded HTTP callback consumed by Google's token verification transport."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> Response:
        """Perform one bounded certificate request for token verification."""
        ...


class ControlAssertionError(ValueError):
    """A controller assertion failed verification. The message carries no token material."""


_UNAUTHORIZED = "control.unauthorized"


def verify_google_control_assertion(
    assertion: str, *, audience: str, expected_subject: str, expected_subject_id: str, request: GoogleRequest
) -> None:
    """Bind the verified email and immutable Google subject to applied identity."""
    from google.oauth2.id_token import verify_oauth2_token

    try:
        if (
            not assertion.startswith("Bearer ")
            or len(assertion) > 16_384
            or not re.fullmatch(r"\d{10,32}", expected_subject_id, flags=re.ASCII)
        ):
            raise ValueError
        claims = verify_oauth2_token(assertion[7:], request, audience=audience)
        if (
            claims.get("email") != expected_subject
            or claims.get("email_verified") is not True
            or claims.get("sub") != expected_subject_id
        ):
            raise ValueError
    except Exception:  # noqa: BLE001  # fail-closed check; token errors can echo the bearer assertion
        raise ControlAssertionError(_UNAUTHORIZED) from None
