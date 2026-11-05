"""Read-only, bounded GCP project inventory through the existing ADC identity."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from copy import deepcopy
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import quote

from pydantic import TypeAdapter
from shared.gcp_range_projects import (
    MAX_BASELINE_BYTES,
    GcpProjectState,
    GcpSecretState,
    GcpServiceAccountState,
    JsonObject,
    ProjectID,
)
from shifter_adapter_sdk.runtime import decode_message

from cloud.gcp.base import import_google_module

if TYPE_CHECKING:
    from requests import Session

_UNAVAILABLE = "Registered project inventory is unavailable"
_JSON = TypeAdapter(JsonObject)
_RM = "https://cloudresourcemanager.googleapis.com/v3/"
_IAM = "https://iam.googleapis.com/v1/"
_SECRETS = "https://secretmanager.googleapis.com/v1/"
_MAX_PAGE_BYTES = 1_048_576
_GET_IAM_POLICY = ":getIamPolicy"


class ProjectInventory(Protocol):
    """The worker may capture metadata, never existing secret payloads or keys."""

    def read(self, project_id: str) -> GcpProjectState:
        """Return complete managed metadata or fail without a partial inventory."""
        ...


class GcpProjectInventory:
    """Use documented REST reads with Google's ADC transport; no provider mutations."""

    def __init__(self, session: Session | None = None) -> None:
        if session is None:
            auth = import_google_module("google.auth")
            transport = import_google_module("google.auth.transport.requests")
            credential, _project = auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = transport.AuthorizedSession(credential)
        if session is None:
            raise ValueError(_UNAVAILABLE)
        self._session = session
        self._remaining = MAX_BASELINE_BYTES

    def read_owned_payload(self, project_number: str, version: str, owned_secrets: set[str]) -> bytes:
        """Access only newly owned versions; registration never calls this route."""
        match = re.fullmatch(
            r"projects/([1-9]\d+)/secrets/([A-Za-z0-9_-]+)/versions/([1-9]\d*)", version, flags=re.ASCII
        )
        if match is None or match[1] != project_number or match[2] not in owned_secrets:
            raise ValueError(_UNAVAILABLE)
        self._remaining = MAX_BASELINE_BYTES
        result = self._read(_SECRETS + version + ":access")
        try:
            if result.get("name") != version:
                raise ValueError()
            payload = result.get("payload")
            if not isinstance(payload, dict):
                raise ValueError()
            data = payload.get("data")
            if not isinstance(data, str):
                raise ValueError()
            material = base64.b64decode(data, validate=True)
            if len(material) > 65536:
                raise ValueError()
            return material
        except (KeyError, TypeError, ValueError):
            raise ValueError(_UNAVAILABLE) from None

    def restore_policy(self, project_number: str, policy: JsonObject, current: JsonObject) -> None:
        """Restore the exact baseline policy after owned grants have been removed."""
        if not project_number.isdecimal() or not current.get("etag"):
            raise ValueError(_UNAVAILABLE)
        restored = deepcopy(policy)
        restored["etag"], restored["version"] = current["etag"], 3
        self._remaining = MAX_BASELINE_BYTES
        self._read(
            _RM + f"projects/{project_number}:setIamPolicy",
            body={"policy": restored, "updateMask": "bindings,auditConfigs"},
        )

    def read(self, project_id: str) -> GcpProjectState:
        """Enumerate every managed object, requesting IAM policy version three."""
        self._remaining = MAX_BASELINE_BYTES
        identifier = TypeAdapter(ProjectID).validate_python(project_id)
        project = self._read(_RM + "projects/" + identifier)
        if project.get("projectId") != identifier or project.get("state") != "ACTIVE":
            raise ValueError(_UNAVAILABLE)
        name = project.get("name")
        if not isinstance(name, str) or not name.startswith("projects/") or not name[9:].isdigit():
            raise ValueError(_UNAVAILABLE)
        policy = self._read(_RM + name + _GET_IAM_POLICY, body={"options": {"requestedPolicyVersion": 3}})
        accounts = self._accounts(identifier)
        secrets = self._secrets(name)
        return GcpProjectState(project=project, policy=policy, service_accounts=accounts, secrets=secrets)

    def _accounts(self, identifier: str) -> dict[str, GcpServiceAccountState]:
        """Read account metadata, policies and user-managed key metadata in the selected project."""
        accounts: dict[str, GcpServiceAccountState] = {}
        for account in self._pages(_IAM + f"projects/{identifier}/serviceAccounts", "accounts", 1024):
            account_name = self._resource_name(account, f"projects/{identifier}/serviceAccounts/")
            email = account.get("email")
            if not isinstance(email, str) or email in accounts:
                raise ValueError(_UNAVAILABLE)
            account_policy = self._read(
                _IAM + quote(account_name, safe="/@") + _GET_IAM_POLICY,
                method="POST",
                params={"options.requestedPolicyVersion": "3"},
            )
            keys = self._read(_IAM + quote(account_name, safe="/@") + "/keys", params={"keyTypes": "USER_MANAGED"})
            raw_keys = keys.get("keys", [])
            if not isinstance(raw_keys, list) or any(not isinstance(key, dict) for key in raw_keys):
                raise ValueError(_UNAVAILABLE)
            accounts[email] = GcpServiceAccountState(
                resource=account, policy=account_policy, user_keys=[_JSON.validate_python(key) for key in raw_keys]
            )
        return accounts

    def _secrets(self, name: str) -> dict[str, GcpSecretState]:
        """Read secret metadata and version identities without accessing baseline payloads."""
        secrets: dict[str, GcpSecretState] = {}
        for secret in self._pages(_SECRETS + name + "/secrets", "secrets", 1024):
            secret_name = self._resource_name(secret, name + "/secrets/")
            if secret_name in secrets:
                raise ValueError(_UNAVAILABLE)
            secret_policy = self._read(
                _SECRETS + quote(secret_name, safe="/") + _GET_IAM_POLICY,
                params={"options.requestedPolicyVersion": "3"},
            )
            versions: dict[str, JsonObject] = {}
            for version in self._pages(_SECRETS + quote(secret_name, safe="/") + "/versions", "versions", 4096):
                version_name = self._resource_name(version, secret_name + "/versions/")
                if version_name in versions:
                    raise ValueError(_UNAVAILABLE)
                versions[version_name] = version
            secrets[secret_name] = GcpSecretState(resource=secret, policy=secret_policy, versions=versions)
        return secrets

    @staticmethod
    def _resource_name(value: JsonObject, prefix: str) -> str:
        """A provider response cannot redirect the next read outside the selected project."""
        name = value.get("name")
        if not isinstance(name, str) or not name.startswith(prefix):
            raise ValueError(_UNAVAILABLE)
        leaf = name.removeprefix(prefix)
        if not leaf or any(char in leaf for char in "/?#%") or ".." in leaf:
            raise ValueError(_UNAVAILABLE)
        return name

    def _pages(self, url: str, field: str, limit: int) -> Iterator[JsonObject]:
        """Bound object count and pagination; an error never becomes an empty page."""
        token, count = "", 0
        seen: set[str] = set()
        while True:
            page = self._read(url, params={"pageSize": "100", "pageToken": token})
            rows = page.get(field, [])
            if not isinstance(rows, list):
                raise ValueError(_UNAVAILABLE)
            count += len(rows)
            if count > limit:
                raise ValueError(_UNAVAILABLE)
            for row in rows:
                yield _JSON.validate_python(row)
            next_token = page.get("nextPageToken", "")
            if not isinstance(next_token, str) or next_token in seen or len(seen) >= 256:
                raise ValueError(_UNAVAILABLE)
            if not next_token:
                break
            token = next_token
            seen.add(token)

    def _read(
        self,
        url: str,
        *,
        method: Literal["GET", "POST"] = "GET",
        params: dict[str, str] | None = None,
        body: JsonObject | None = None,
    ) -> JsonObject:
        """No redirects, unbounded responses, raw provider errors or secret-access routes."""
        try:
            with self._session.request(
                "POST" if body is not None else method,
                url,
                params=params,
                json=body,
                timeout=(10, 30),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise ValueError(_UNAVAILABLE)
                material = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    material.extend(chunk)
                    if len(material) > min(_MAX_PAGE_BYTES, self._remaining):
                        raise ValueError(_UNAVAILABLE)
                self._remaining -= len(material)
                return _JSON.validate_python(decode_message(bytes(material), limit=_MAX_PAGE_BYTES))
        except Exception:  # noqa: BLE001  # auth/HTTP and metadata failures never disclose provider data or proof
            raise ValueError(_UNAVAILABLE) from None
