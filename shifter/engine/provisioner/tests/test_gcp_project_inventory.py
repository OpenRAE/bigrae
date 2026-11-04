"""Metadata inventory must be complete, scoped, bounded and read-only."""

import base64
import json

import pytest

from gcp_project_inventory import GcpProjectInventory

_PROJECT = "synthetic-project"
_NUMBER = "123456789012"
_ACCOUNT = f"projects/{_PROJECT}/serviceAccounts/reader@{_PROJECT}.iam.gserviceaccount.com"
_SECRET = f"projects/{_NUMBER}/secrets/example"


class Response:
    def __init__(self, body, status=200):
        self.material = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.material), chunk_size):
            yield self.material[offset : offset + chunk_size]


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        token = (kwargs.get("params") or {}).get("pageToken", "")
        response = self.routes[(url, token)]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def routes():
    rm = "https://cloudresourcemanager.googleapis.com/v3/"
    iam = "https://iam.googleapis.com/v1/"
    sm = "https://secretmanager.googleapis.com/v1/"
    return {
        (rm + f"projects/{_PROJECT}", ""): Response(
            {"projectId": _PROJECT, "name": f"projects/{_NUMBER}", "state": "ACTIVE"}
        ),
        (rm + f"projects/{_NUMBER}:getIamPolicy", ""): Response({"version": 3, "etag": "project", "bindings": []}),
        (iam + f"projects/{_PROJECT}/serviceAccounts", ""): Response(
            {
                "accounts": [
                    {"name": _ACCOUNT, "email": f"reader@{_PROJECT}.iam.gserviceaccount.com", "uniqueId": "123"}
                ],
                "nextPageToken": "second",
            }
        ),
        (iam + f"projects/{_PROJECT}/serviceAccounts", "second"): Response({}),
        (iam + _ACCOUNT + ":getIamPolicy", ""): Response({"version": 3, "bindings": []}),
        (iam + _ACCOUNT + "/keys", ""): Response(
            {"keys": [{"name": _ACCOUNT + "/keys/example", "keyType": "USER_MANAGED"}]}
        ),
        (sm + f"projects/{_NUMBER}/secrets", ""): Response(
            {"secrets": [{"name": _SECRET, "replication": {"automatic": {}}}]}
        ),
        (sm + _SECRET + ":getIamPolicy", ""): Response({"version": 3, "bindings": []}),
        (sm + _SECRET + "/versions", ""): Response(
            {"versions": [{"name": _SECRET + "/versions/1", "state": "ENABLED"}], "nextPageToken": "second"}
        ),
        (sm + _SECRET + "/versions", "second"): Response(
            {"versions": [{"name": _SECRET + "/versions/2", "state": "DISABLED"}]}
        ),
    }


def test_inventory_paginates_all_metadata_and_never_reads_values_or_creates_keys(routes):
    session = Session(routes)
    state = GcpProjectInventory(session).read(_PROJECT)
    assert state.project["name"] == f"projects/{_NUMBER}"
    assert len(state.service_accounts) == 1
    assert len(state.secrets[_SECRET].versions) == 2
    assert state.secrets[_SECRET].versions[_SECRET + "/versions/2"]["state"] == "DISABLED"
    for method, url, kwargs in session.calls:
        assert method == "GET" or (method == "POST" and url.endswith(":getIamPolicy"))
        assert not any(term in url for term in (":access", ":create", ":enable", ":destroy", ":setIamPolicy"))
        if url.endswith(":getIamPolicy"):
            if method == "POST":
                assert kwargs["json"] == {"options": {"requestedPolicyVersion": 3}}
            else:
                assert kwargs["params"] == {"options.requestedPolicyVersion": "3"}
        if url.endswith("/keys"):
            assert kwargs["params"] == {"keyTypes": "USER_MANAGED"}


@pytest.mark.parametrize("version", ["1\u0661", "\u0661", "1/../2", "1?alt=json"])
def test_owned_payload_path_rejects_non_ascii_digits_and_path_extensions_before_http(version):
    session = Session({})
    with pytest.raises(ValueError, match="inventory is unavailable"):
        GcpProjectInventory(session).read_owned_payload(_NUMBER, f"{_SECRET}/versions/{version}", {"example"})
    assert not session.calls


@pytest.mark.parametrize("size", [0, 65536, 65537])
def test_owned_payload_read_keeps_the_provider_byte_limit(size):
    version = f"{_SECRET}/versions/1"
    url = f"https://secretmanager.googleapis.com/v1/{version}:access"
    material = b"x" * size
    session = Session(
        {(url, ""): Response({"name": version, "payload": {"data": base64.b64encode(material).decode()}})}
    )
    reader = GcpProjectInventory(session)
    if size > 65536:
        with pytest.raises(ValueError, match="inventory is unavailable"):
            reader.read_owned_payload(_NUMBER, version, {"example"})
    else:
        assert reader.read_owned_payload(_NUMBER, version, {"example"}) == material
    assert len(session.calls) == 1 and session.calls[0][:2] == ("GET", url)


def test_policy_restoration_uses_current_etag_and_preserves_the_original_policy():
    url = f"https://cloudresourcemanager.googleapis.com/v3/projects/{_NUMBER}:setIamPolicy"
    original = {"version": 1, "etag": "original", "bindings": [], "auditConfigs": []}
    session = Session({(url, ""): Response({})})
    GcpProjectInventory(session).restore_policy(_NUMBER, original, {"etag": "current"})
    method, actual_url, options = session.calls[0]
    assert (method, actual_url) == ("POST", url)
    assert options["json"] == {
        "policy": {**original, "version": 3, "etag": "current"},
        "updateMask": "bindings,auditConfigs",
    }
    assert original["etag"] == "original" and original["version"] == 1


@pytest.mark.parametrize("status", [302, 403, 404, 429, 500])
def test_any_failed_list_or_policy_read_refuses_the_whole_inventory(routes, status):
    key = next(key for key in routes if key[0].endswith("/secrets"))
    routes[key] = Response({"error": "private provider diagnostic"}, status)
    with pytest.raises(ValueError, match=r"^Registered project inventory is unavailable$"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)


def test_pagination_loop_is_not_silently_truncated(routes):
    key = next(key for key in routes if key[0].endswith("/serviceAccounts") and key[1] == "second")
    routes[key] = Response({"nextPageToken": "second"})
    with pytest.raises(ValueError, match="unavailable"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)


@pytest.mark.parametrize("field", ["name", "projectId", "state"])
def test_inventory_cannot_switch_projects_or_capture_a_deleted_project(routes, field):
    key = next(iter(routes))
    value = json.loads(routes[key].material)
    value[field] = {"name": "projects/another", "projectId": "another-project", "state": "DELETE_REQUESTED"}[field]
    routes[key] = Response(value)
    with pytest.raises(ValueError, match="unavailable"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)


def test_provider_resource_cannot_redirect_followup_reads_to_another_project(routes):
    key = next(key for key in routes if key[0].endswith("/secrets"))
    routes[key] = Response({"secrets": [{"name": "projects/other/secrets/private"}]})
    with pytest.raises(ValueError, match="unavailable"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)


@pytest.mark.parametrize("raw", [b'{"accounts":[],"accounts":[]}', b"x" * 1_048_577])
def test_ambiguous_or_oversized_provider_response_is_refused(routes, raw):
    key = next(key for key in routes if key[0].endswith("/serviceAccounts") and not key[1])
    routes[key] = Response(raw)
    with pytest.raises(ValueError, match="unavailable"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)


def test_aggregate_inventory_budget_bounds_memory_across_individually_valid_pages(routes):
    keys = list(routes)
    project = json.loads(routes[keys[0]].material)
    project["displayName"] = "x" * 600_000
    routes[keys[0]] = Response(project)
    routes[keys[1]] = Response({"version": 3, "bindings": [], "etag": "x" * 600_000})
    with pytest.raises(ValueError, match="unavailable"):
        GcpProjectInventory(Session(routes)).read(_PROJECT)
