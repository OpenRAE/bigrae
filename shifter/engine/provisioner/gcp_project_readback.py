"""Compare independent provider inventory with native intent and retained Terraform identities."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from shared.gcp_range_projects import GcpProjectBaseline, GcpProjectState, GcpSecretState, require_project_parity
from shared.gcp_runtime_plan import GcpProjectWork
from shifter_adapter_sdk.runtime import canonical_digest

from gcp_project_terraform import resource_key

_MISMATCH = "Registered project readback does not match its declared state"


def terraform_resources(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Only this generated root module owns resources; child modules are forbidden."""
    root = state.get("values", {}).get("root_module", {})
    if root.get("child_modules"):
        raise ValueError(_MISMATCH)
    rows = root.get("resources", [])
    result = {row["address"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(_MISMATCH)
    return result


def _values(resources: dict[str, Any], kind: str, identity: str) -> dict[str, Any]:
    """Locate one generated managed resource by its retained logical identity."""
    row = resources.get(kind + "." + resource_key(identity))
    if row is None or row.get("mode") != "managed":
        raise ValueError(_MISMATCH)
    return row["values"]


def expected_project_policy(work: GcpProjectWork, baseline: GcpProjectBaseline) -> dict[str, Any]:
    """Overlay declared grants/audit settings while preserving every baseline grant."""
    expected: dict[str, Any] = deepcopy(baseline.state.policy)
    for grant in work.grants:
        if grant["kind"] == "project":
            _add_grant(expected, grant)
    for audit in work.audits:
        configs = expected.setdefault("auditConfigs", [])
        service = next((row for row in configs if row["service"] == audit["service"]), None)
        if service is None:
            service = {"service": audit["service"], "auditLogConfigs": []}
            configs.append(service)
        rows = service.setdefault("auditLogConfigs", [])
        row = next((row for row in rows if row["logType"] == audit["log_type"]), None)
        if row is None:
            row = {"logType": audit["log_type"]}
            rows.append(row)
        if audit["exempted_members"]:
            row["exemptedMembers"] = sorted(set(row.get("exemptedMembers", [])) | set(audit["exempted_members"]))
    return expected


def _add_grant(policy: dict[str, Any], grant: dict[str, Any]) -> None:
    """Merge one declared member without changing the binding's role or condition."""
    rows = policy.setdefault("bindings", [])
    row = next(
        (row for row in rows if (row["role"], row.get("condition")) == (grant["role"], grant["condition"])), None
    )
    if row is None:
        row = {"role": grant["role"], "members": []}
        if grant["condition"] is not None:
            row["condition"] = deepcopy(grant["condition"])
        rows.append(row)
    if grant["member"] not in row["members"]:
        row["members"].append(grant["member"])


def _policy_equal(expected: dict[str, Any], observed: dict[str, Any]) -> None:
    """Treat omitted empty policy collections as empty, retain all security values."""
    if _normalized_policy(expected) != _normalized_policy(observed):
        raise ValueError(_MISMATCH)


def _normalized_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Remove volatile etags and normalize only order and omitted empty collections."""
    value = deepcopy(policy)
    value.pop("etag", None)
    version = value.pop("version", 0)
    if version not in {0, 1, 3}:
        raise ValueError(_MISMATCH)
    for field in ("bindings", "auditConfigs"):
        rows = value.get(field, [])
        if not rows:
            value.pop(field, None)
            continue
        normalize = _normalized_binding if field == "bindings" else _normalized_audit
        value[field] = sorted([normalize(row) for row in rows], key=canonical_digest)
    return value


def _normalized_binding(row: dict[str, Any]) -> dict[str, Any]:
    """Preserve every binding field while sorting its member collection."""
    row["members"] = sorted(row.get("members", []))
    return row


def _normalized_audit(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize audit order and empty exemptions without discarding policy values."""
    for config in row.get("auditLogConfigs", []):
        if config.get("exemptedMembers"):
            config["exemptedMembers"] = sorted(config["exemptedMembers"])
        else:
            config.pop("exemptedMembers", None)
    row["auditLogConfigs"] = sorted(row.get("auditLogConfigs", []), key=canonical_digest)
    return row


def verify_project_setup(
    work: GcpProjectWork,
    baseline: GcpProjectBaseline,
    actual: GcpProjectState,
    state: dict[str, Any],
    access_payload: Callable[[str], bytes],
) -> None:
    """Check exact resource sets, original incarnations, policy and literal payload bytes."""
    resources = terraform_resources(state)
    from gcp_project_terraform import terraform_document

    document = terraform_document(work, baseline)
    require_recorded_incarnations(work, actual, state, document)
    expected_resources = {f"{kind}.{name}" for kind, rows in document["resource"].items() for name in rows}
    if set(resources) != expected_resources:
        raise ValueError(_MISMATCH)
    remainder = actual.model_copy(deep=True)
    _verify_accounts(work, remainder, resources)
    _verify_secrets(work, remainder, resources, access_payload)
    _policy_equal(expected_project_policy(work, baseline), actual.policy)
    # New resources were individually verified above. The rest must retain the
    # complete original managed surface, including keys and secret incarnations.
    remainder = remainder.model_copy(update={"policy": deepcopy(baseline.state.policy)})
    require_project_parity(baseline.state, remainder)


def _verify_accounts(work: GcpProjectWork, remainder: GcpProjectState, resources: dict[str, Any]) -> None:
    """Verify each owned account and its policy before removing it from the baseline comparison."""
    for email, intent in work.accounts.items():
        recorded = _values(resources, "google_service_account", email)
        account = remainder.service_accounts.pop(email, None)
        if account is None or account.user_keys:
            raise ValueError(_MISMATCH)
        expected = {
            "email": email,
            "projectId": work.lease.project_id,
            "uniqueId": recorded.get("unique_id"),
            "name": recorded.get("name"),
            "displayName": intent["display_name"],
            "description": intent["description"],
            "disabled": intent["disabled"],
        }
        _require_account_metadata(account.resource, expected)
        policy: dict[str, Any] = {}
        for grant in work.grants:
            if (grant["kind"], grant["target"]) == ("service-account", email):
                _add_grant(policy, grant)
        _policy_equal(policy, account.policy)


def _require_account_metadata(observed: dict[str, Any], expected: dict[str, Any]) -> None:
    """Account IDs, incarnations and exact authored metadata must all match readback."""
    for key, value in expected.items():
        if observed.get(key, False if key == "disabled" else "") != value:
            raise ValueError(_MISMATCH)


def _verify_secrets(
    work: GcpProjectWork, remainder: GcpProjectState, resources: dict[str, Any], access_payload: Callable[[str], bytes]
) -> None:
    """Verify complete owned secret metadata, policies, versions and protected payloads."""
    for name, intent in work.secrets.items():
        recorded = _values(resources, "google_secret_manager_secret", name)
        provider_name = f"projects/{work.lease.project_number}/secrets/{name}"
        secret = remainder.secrets.pop(provider_name, None)
        if secret is None or recorded.get("secret_id") != name or secret.resource.get("name") != provider_name:
            raise ValueError(_MISMATCH)
        if secret.resource.get("labels"):
            raise ValueError(_MISMATCH)
        replication = intent["replication"]
        wanted = (
            {"automatic": {}}
            if "auto" in replication
            else {
                "userManaged": {
                    "replicas": [{"location": row["location"]} for row in replication["user_managed"]["replicas"]]
                }
            }
        )
        if secret.resource.get("replication") != wanted:
            raise ValueError(_MISMATCH)
        policy: dict[str, Any] = {}
        for grant in work.grants:
            if (grant["kind"], grant["target"]) == ("secret", name):
                _add_grant(policy, grant)
        _policy_equal(policy, secret.policy)
        _verify_versions(name, intent, secret, resources, access_payload)


def require_recorded_incarnations(
    work: GcpProjectWork, actual: GcpProjectState, state: dict[str, Any], document: dict[str, Any]
) -> None:
    """A delete/recreate under the same email/name cannot authorize deletion."""
    resources = terraform_resources(state)
    if (
        actual.project.get("name") != f"projects/{work.lease.project_number}"
        or actual.project.get("projectId") != work.lease.project_id
    ):
        raise ValueError(_MISMATCH)
    expected = {f"{kind}.{name}" for kind, rows in document["resource"].items() for name in rows}
    if not resources.keys() <= expected:
        raise ValueError(_MISMATCH)
    _require_recorded_scope(work, resources)
    _require_account_incarnations(work, actual, resources)
    _require_secret_incarnations(work, actual, resources)


def _require_account_incarnations(work: GcpProjectWork, actual: GcpProjectState, resources: dict[str, Any]) -> None:
    """A reused account email cannot confer ownership of a replacement account."""
    for email in work.accounts:
        row = resources.get("google_service_account." + resource_key(email))
        current = actual.service_accounts.get(email)
        if (
            row is not None
            and current is not None
            and current.resource.get("uniqueId") != row["values"].get("unique_id")
        ):
            raise ValueError(_MISMATCH)


def _require_secret_incarnations(work: GcpProjectWork, actual: GcpProjectState, resources: dict[str, Any]) -> None:
    """A secret replacement must retain its own creation identity outside this lease."""
    for name in work.secrets:
        row = resources.get("google_secret_manager_secret." + resource_key(name))
        current = actual.secrets.get(f"projects/{work.lease.project_number}/secrets/{name}")
        if (
            row is not None
            and current is not None
            and current.resource.get("createTime") != row["values"].get("create_time")
        ):
            raise ValueError(_MISMATCH)


def verify_policy_after_destroy(work: GcpProjectWork, baseline: GcpProjectBaseline, actual: GcpProjectState) -> None:
    """Do not erase an unrelated out-of-band policy change while restoring audits."""
    expected: dict[str, Any] = deepcopy(baseline.state.policy)
    managed_services = {audit["service"] for audit in work.audits}
    if "auditConfigs" in expected:
        expected["auditConfigs"] = [row for row in expected["auditConfigs"] if row["service"] not in managed_services]
    _policy_equal(expected, actual.policy)


def _verify_versions(
    name: str,
    intent: dict[str, Any],
    secret: GcpSecretState,
    resources: dict[str, Any],
    access_payload: Callable[[str], bytes],
) -> None:
    """Compare every new version and its literal payload through independent reads."""
    versions = set()
    for version in intent["versions"]:
        values = _values(resources, "google_secret_manager_secret_version", name + "/" + version["version_id"])
        version_name = values.get("name")
        if not isinstance(version_name, str):
            raise ValueError(_MISMATCH)
        metadata = secret.versions.get(version_name)
        if metadata is None or metadata.get("state") != ("ENABLED" if version["enabled"] else "DISABLED"):
            raise ValueError(_MISMATCH)
        if not version["enabled"] or access_payload(version_name) != version["payload"]:
            raise ValueError(_MISMATCH)
        versions.add(version_name)
    if versions != set(secret.versions):
        raise ValueError(_MISMATCH)


def _require_recorded_scope(work: GcpProjectWork, resources: dict[str, dict[str, Any]]) -> None:
    """Refuse foreign providers, projects, members and roles before Terraform effects."""
    grants = {resource_key(canonical_digest(row)): row for row in work.grants}
    for address, resource in resources.items():
        values = resource["values"]
        if (
            resource.get("mode") != "managed"
            or resource.get("provider_name") != "registry.terraform.io/hashicorp/google"
        ):
            raise ValueError(_MISMATCH)
        if values.get("project") is not None and str(values["project"]) not in {
            work.lease.project_id,
            work.lease.project_number,
        }:
            raise ValueError(_MISMATCH)
        if resource["type"].endswith("_iam_member"):
            grant = grants.get(address.split(".", 1)[1])
            if grant is None or (values.get("role"), values.get("member")) != (grant["role"], grant["member"]):
                raise ValueError(_MISMATCH)
