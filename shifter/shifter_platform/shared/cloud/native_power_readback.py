"""Observe GCE's exact completed request; never issue or retry a power mutation."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from shared.model_access.messages import strict_json
from shared.native_participant import NativePowerInvocationGrant
from shared.native_power import parse_gce_resource_identity

from .gcp.base import import_google_module

_ORIGIN = "https://compute.googleapis.com/compute/v1/"
_FIELDS = "nextPageToken,items(name,clientOperationId,operationType,targetId,targetLink,status)"
_MAX_BYTES = 32_768


def _sole_operation(value: object) -> dict[str, object] | None:
    """Reject pagination, absence, and ambiguity before matching a provider request."""
    if not isinstance(value, dict) or value.get("nextPageToken"):
        return None
    items = value.get("items", [])
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    return items[0]


def _completed_operation(value: object, grant: NativePowerInvocationGrant) -> str | None:
    operation = _sole_operation(value)
    if operation is None:
        return None
    target = grant.target
    suffix = f"projects/{target.project_id}/zones/{target.zone}/instances/{target.instance_name}"
    links = {suffix, _ORIGIN + suffix, "https://www.googleapis.com/compute/v1/" + suffix}
    name = operation.get("name")
    if (
        operation.get("clientOperationId") != str(grant.invocation_id)
        or operation.get("operationType") != ("stop" if grant.verb == "pause" else "start")
        or operation.get("status") != "DONE"
        or operation.get("targetLink") not in links
        or parse_gce_resource_identity(operation.get("targetId")) != grant.incarnation.instance_identity
        or not isinstance(name, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,255}", name) is None
    ):
        return None
    return f"projects/{target.project_id}/zones/{target.zone}/operations/{name}"


class GCENativePowerObserver:
    """Use the installed application identity and a fixed authenticated HTTPS origin."""

    def __init__(self, *, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory or _authorized_session

    def completed_call(self, grant: NativePowerInvocationGrant) -> str | None:
        """Return only exact completed-call evidence; preserve every uncertainty."""
        if not isinstance(grant, NativePowerInvocationGrant) or grant.verb not in {"pause", "resume"}:
            return None
        try:
            return _completed_operation(self._read_call(grant), grant)
        except Exception:  # noqa: BLE001  # uncertainty retains exclusion; no provider diagnostics escape
            return None

    def _read_call(self, grant: NativePowerInvocationGrant) -> object:
        """Read only the fixed exact-request operation list with bounded transport."""
        target = grant.target
        with (
            self._session_factory() as session,
            session.get(
                _ORIGIN + f"projects/{target.project_id}/zones/{target.zone}/operations",
                params={
                    "filter": f'clientOperationId = "{grant.invocation_id}"',
                    "maxResults": 2,
                    "fields": _FIELDS,
                },
                timeout=(1, 2),
                allow_redirects=False,
                stream=True,
            ) as response,
        ):
            if response.status_code != 200:
                raise ValueError("Native cloud observation unavailable")
            payload = strict_json(response.raw.read(_MAX_BYTES + 1), limit=_MAX_BYTES)
        return payload


@contextmanager
def _authorized_session() -> Iterator[Any]:
    """No environment proxy or CA override, and bounded credential refresh."""
    import requests

    google_auth = import_google_module("google.auth")
    transport = import_google_module("google.auth.transport.requests")
    with requests.Session() as authentication_session:
        authentication_session.trust_env = False
        request = transport.Request(session=authentication_session)

        def bounded_request(*args: object, **kwargs: object) -> object:
            kwargs["timeout"] = 2
            return request(*args, **kwargs)

        credentials, _ = google_auth.default(
            scopes=["https://www.googleapis.com/auth/compute.readonly"],
            request=bounded_request,
        )
        with transport.AuthorizedSession(
            credentials,
            auth_request=bounded_request,
            refresh_timeout=2,
            max_refresh_attempts=0,
        ) as session:
            session.trust_env = False
            yield session
