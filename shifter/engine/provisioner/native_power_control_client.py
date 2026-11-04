"""Private native invocation transport with fixed TLS, routing and workload proof."""

from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import IO, NoReturn
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, ProxyHandler, Request, build_opener
from uuid import UUID

from shared.model_access.messages import strict_json
from shared.native_participant import NativePowerInvocationGrant
from shared.native_power_protocol import NATIVE_POWER_TOKEN_DIRECTORY, parse_native_power_grant
from shared.participant_control_installation import NativeControlInstallation

_TOKEN_PATH = Path(NATIVE_POWER_TOKEN_DIRECTORY) / "token"
_MAX_RESPONSE = 32_768


class NativePowerTransportError(RuntimeError):
    """A private protocol failure; no source, token or provider diagnostics leave it."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> NoReturn:
        raise ValueError("Native invocation redirect refused")


@dataclass(frozen=True, slots=True)
class NativePowerControlClient:
    """Only fixed installation code constructs the native owner transport."""

    installation: NativeControlInstallation = field(repr=False)
    _opener: OpenerDirector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cadata=self.installation.trust_ca_pem)
        object.__setattr__(
            self, "_opener", build_opener(ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect())
        )

    @classmethod
    def from_environment(cls) -> NativePowerControlClient:
        """Deployment configuration cannot select executable code or an arbitrary origin."""
        try:
            raw = os.environ["PARTICIPANT_CONTROL_CONFIGURATION"].encode()
            return cls(NativeControlInstallation.model_validate(strict_json(raw, limit=32_768)))
        except Exception:  # noqa: BLE001  # never echo an invalid deployment body
            raise NativePowerTransportError("Native invocation transport unavailable") from None

    @staticmethod
    def _token() -> str:
        with _TOKEN_PATH.open("rb") as stream:
            encoded = stream.read(12_289)
        token = encoded.decode("ascii").strip()
        if not token or len(encoded) > 12_288 or any(char.isspace() for char in token):
            raise ValueError("Native workload authentication unavailable")
        return token

    def _post(self, action: str, payload: dict[str, str], *, expected_status: int) -> dict[str, object] | None:
        try:
            request = Request(  # noqa: S310  # fixed private HTTPS origin; redirects and environment proxies are disabled
                self.installation.control_origin + f"/internal/participant-control/invocations/{action}/",
                data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._token()},
            )
            with self._opener.open(request, timeout=5) as response:
                if response.status != expected_status:
                    raise ValueError
                if expected_status == 204:
                    return None
                return strict_json(response.read(_MAX_RESPONSE + 1), limit=_MAX_RESPONSE)
        except Exception:  # noqa: BLE001  # a lost reply is never a second invocation permission
            raise NativePowerTransportError("Native invocation transport unavailable") from None

    def acquire(self, operation_id: UUID, member_ref: str, attempt_id: UUID) -> NativePowerInvocationGrant:
        """Acquire once; no retry can turn an unknown response into another cloud call."""
        try:
            return parse_native_power_grant(
                self._post(
                    "begin",
                    {"operation_id": str(operation_id), "member_ref": member_ref, "attempt_id": str(attempt_id)},
                    expected_status=200,
                )
            )
        except Exception:  # noqa: BLE001  # malformed responses remain private and cannot reach the provider
            raise NativePowerTransportError("Native invocation transport unavailable") from None

    def complete(self, invocation_id: UUID, attempt_id: UUID) -> None:
        """Acknowledge this worker's cessation separately from world/readiness evidence."""
        self._post("finish", {"invocation_id": str(invocation_id), "attempt_id": str(attempt_id)}, expected_status=204)

    def withdraw(self, operation_id: UUID, member_ref: str, attempt_id: UUID) -> None:
        """Fence a pre-call attempt, including an acquisition whose response was lost."""
        self._post(
            "withdraw",
            {
                "operation_id": str(operation_id),
                "member_ref": member_ref,
                "attempt_id": str(attempt_id),
            },
            expected_status=204,
        )
