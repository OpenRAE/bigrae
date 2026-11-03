"""Lower supported native cloud declarations into provider operations, without RAES imports.

These are process-local execution arguments. The original native plan remains
the sole intent and is retained unchanged beside its project leases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from shifter_adapter_sdk.runtime import RuntimePlan

from shared.gcp_range_projects import GcpProjectLease
from shared.gcp_runtime_types import UNSUPPORTED, GcpProjectWork, SubjectMap, TargetMap, records, supported, token


def native_cloud_nodes(plan: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Read the public planned-node payload, retaining its native reference names."""
    result = []
    for address, resource in plan.get("resources", {}).items():
        if resource.get("resource_type") != "node":
            continue
        payload = resource["payload"]
        runtime = payload.get("spec", {}).get("node", {}).get("runtime")
        if runtime is None:
            continue
        if not isinstance(runtime, dict):
            raise ValueError(UNSUPPORTED)
        authorities = records(runtime.get("identity_authorities", []))
        applications = records(runtime.get("platform_applications", []))
        if authorities or applications:
            result.append((str(address), token(payload.get("node_name", payload.get("name"))), runtime))
    return result


def compile_cloud_work(
    plan: Mapping[str, Any], leases: Sequence[GcpProjectLease], contents: Mapping[str, bytes]
) -> tuple[GcpProjectWork, ...]:
    """Validate the complete supported graph before a provider or guest effect."""
    from shared.gcp_runtime_secrets import compile_secret_application

    work = {lease.project_id: GcpProjectWork(lease) for lease in leases}
    if len(work) != len(leases):
        raise ValueError(UNSUPPORTED)
    scopes: dict[str, GcpProjectWork] = {}
    subjects: dict[str, tuple[dict[str, Any], GcpProjectWork | None, str]] = {}
    targets: dict[str, tuple[GcpProjectWork, str, str]] = {}
    authorities = []
    nodes = native_cloud_nodes(plan)
    for address, name, runtime in nodes:
        for authority in records(runtime.get("identity_authorities", [])):
            prefix = f"nodes.{name}.runtime.identity_authorities.{token(authority.get('identity_authority_id'))}"
            _authority(authority, prefix, work, scopes, targets)
            authorities.append((address, prefix, authority))
    for _address, prefix, authority in authorities:
        for subject in records(authority.get("subjects", [])):
            _subject(subject, prefix, scopes, subjects, targets)
    for _address, name, runtime in nodes:
        for application in records(runtime.get("platform_applications", [])):
            compile_secret_application(application, name, scopes, contents, targets)
    for _address, prefix, authority in authorities:
        _policies(authority, subjects, targets)
        _identity_uses(authority, subjects, plan)
        _audits(authority, prefix, scopes, subjects)
    used = {item.lease.project_id for item in scopes.values()}
    if used != set(work):
        raise ValueError(UNSUPPORTED)
    return tuple(work[key] for key in sorted(work))


def _authority(
    authority: dict[str, Any],
    prefix: str,
    work: dict[str, GcpProjectWork],
    scopes: dict[str, GcpProjectWork],
    targets: TargetMap,
) -> None:
    supported(
        authority,
        {"identity_authority_id", "kind", "resource_scopes", "subjects", "policies", "identity_uses"},
        {
            "name": "",
            "namespace": "",
            "domain_name": "",
            "realm": "",
            "issuer": "",
            "tenant_id": "",
            "base_dn": "",
            "description": "",
            "services": [],
            "relationships": [],
            "access_observations": [],
        },
    )
    if authority.get("kind") != "cloud_iam":
        raise ValueError(UNSUPPORTED)
    for scope in records(authority.get("resource_scopes", [])):
        supported(
            scope,
            {"scope_id", "provider", "scope_kind", "native_id", "incarnation_id", "audit_logs"},
            {"name": "", "parent_ref": "", "description": ""},
        )
        project = work.get(scope.get("native_id", ""))
        if (
            project is None
            or scope.get("provider") != "gcp"
            or scope.get("scope_kind") != "project"
            or scope.get("incarnation_id", "") not in {"", project.lease.project_number}
        ):
            raise ValueError(UNSUPPORTED)
        ref = f"{prefix}.resource_scopes.{token(scope.get('scope_id'))}"
        if ref in scopes:
            raise ValueError(UNSUPPORTED)
        scopes[ref] = project
        targets[ref] = (project, "project", project.lease.project_id)


def _subject(
    subject: dict[str, Any], prefix: str, scopes: dict[str, GcpProjectWork], subjects: SubjectMap, targets: TargetMap
) -> None:
    supported(
        subject,
        {
            "subject_id",
            "kind",
            "name",
            "principal_name",
            "display_name",
            "description",
            "enabled",
            "resource_scope_ref",
            "origin",
        },
        {"distinguished_name": "", "domain": "", "service_principal_names": [], "attributes": []},
    )
    ref = f"{prefix}.subjects.{token(subject.get('subject_id'))}"
    kind = token(subject.get("kind"))
    project = scopes.get(subject.get("resource_scope_ref", ""))
    if ref in subjects or not isinstance(subject.get("name"), str):
        raise ValueError(UNSUPPORTED)
    if kind == "role":
        member = token(subject["name"], r"roles/[A-Za-z0-9_.]{1,128}")
    elif kind == "service_account" and project is not None:
        identity = subject.get("principal_name") or subject["name"]
        if "@" not in identity:
            identity = f"{identity}@{project.lease.project_id}.iam.gserviceaccount.com"
        account_id = token(identity.split("@", 1)[0], r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
        if (
            identity != f"{account_id}@{project.lease.project_id}.iam.gserviceaccount.com"
            or identity in project.accounts
        ):
            raise ValueError(UNSUPPORTED)
        member = "serviceAccount:" + identity
        project.accounts[identity] = {
            "account_id": account_id,
            "display_name": subject.get("display_name", ""),
            "description": subject.get("description", ""),
            "disabled": subject.get("enabled") is False,
        }
        targets[ref] = (project, "service-account", identity)
    else:
        member = subject.get("principal_name") or subject["name"]
        patterns = {
            "service_account": (
                r"serviceAccount:(?:[^\s/@]+@[^\s/]+\.iam\.gserviceaccount\.com|"
                r"[a-z0-9-]+\.svc\.id\.goog\[[a-z0-9-]+/[a-z0-9-]+\])"
            ),
            "user": r"user:[^\s@]+@[^\s@]+",
            "group": r"group:[^\s@]+@[^\s@]+",
            "service_principal": (
                r"(?:(?:principal|principalSet)://iam\.googleapis\.com/[^\s]+|"
                r"serviceAccount:[a-z0-9-]+\.svc\.id\.goog\[[a-z0-9-]+/[a-z0-9-]+\])"
            ),
        }
        token(member, patterns.get(kind, r"(?!)"))
        if subject.get("enabled") is False or subject.get("display_name") or subject.get("description"):
            raise ValueError(UNSUPPORTED)
    subjects[ref] = (subject, project, member)


def _principal(ref: str, subjects: SubjectMap) -> str:
    found = subjects.get(ref)
    if found is None or found[0].get("kind") == "role":
        raise ValueError(UNSUPPORTED)
    return found[2]


def selected_secret_payloads(plan: Mapping[str, Any], result: RuntimePlan, concerns: Sequence[str]) -> dict[str, bytes]:
    """Payload omission is open; an explicit native Content reference remains binding."""
    if not result.secret_payloads:
        return {}
    if "runtime-platform-applications" not in concerns:
        raise ValueError(UNSUPPORTED)
    slots = {}
    for _address, name, runtime in native_cloud_nodes(plan):
        for application in records(runtime.get("platform_applications", [])):
            prefix = f"nodes.{name}.runtime.platform_applications.{application['platform_application_id']}"
            for secret in records(application.get("secrets", [])):
                for version in records(secret.get("versions", [])):
                    ref = f"{prefix}.secrets.{secret['secret_id']}.versions.{version['version_id']}"
                    if ref in slots:
                        raise ValueError(UNSUPPORTED)
                    slots[ref] = version
    selected = {}
    for value in result.secret_payloads:
        slot = slots.get(value.version_ref)
        if slot is None or slot.get("payload_content_ref"):
            raise ValueError(UNSUPPORTED)
        selected[value.version_ref] = value.value.encode("utf-8")
    return selected


def _policies(authority: dict[str, Any], subjects: SubjectMap, targets: TargetMap) -> None:
    for policy in records(authority.get("policies", [])):
        supported(
            policy,
            {"policy_id", "policy_kind", "resource_access"},
            {"name": "", "applies_to_refs": [], "settings": [], "description": ""},
        )
        access = policy.get("resource_access")
        if policy.get("policy_kind") != "access" or not isinstance(access, dict):
            raise ValueError(UNSUPPORTED)
        supported(access, {"attachment_ref", "bindings"}, {"inherited_from_ref": ""})
        target = targets.get(access.get("attachment_ref", ""))
        if target is None:
            raise ValueError(UNSUPPORTED)
        project, kind, identity = target
        for binding in records(access.get("bindings", [])):
            supported(
                binding,
                {"binding_id", "principal_refs", "resource_refs", "role_ref", "effect", "condition", "description"},
                {"actions": []},
            )
            role = subjects.get(binding.get("role_ref", ""))
            if (
                role is None
                or role[0].get("kind") != "role"
                or binding.get("effect") != "allow"
                or binding.get("resource_refs") != [access["attachment_ref"]]
            ):
                raise ValueError(UNSUPPORTED)
            condition = _binding_condition(binding)
            refs = binding.get("principal_refs")
            if not isinstance(refs, list) or not refs:
                raise ValueError(UNSUPPORTED)
            for ref in refs:
                project.grants.append(
                    {
                        "kind": kind,
                        "target": identity,
                        "role": role[2],
                        "member": _principal(ref, subjects),
                        "condition": condition,
                    }
                )


def _identity_uses(authority: dict[str, Any], subjects: SubjectMap, plan: Mapping[str, Any]) -> None:
    names = {
        f"nodes.{row['payload'].get('node_name', row['payload'].get('name'))}": address
        for address, row in plan["resources"].items()
        if row.get("resource_type") == "node" and row["payload"].get("count") in (None, 1)
    }
    for use in records(authority.get("identity_uses", [])):
        supported(
            use, {"use_id", "workload_ref", "principal_ref", "mode"}, {"source_principal_ref": "", "description": ""}
        )
        found = subjects.get(use.get("principal_ref", ""))
        node_address = names.get(use.get("workload_ref", ""))
        if (
            use.get("mode") != "attached"
            or found is None
            or found[1] is None
            or node_address is None
            or found[0].get("kind") != "service_account"
            or found[0].get("enabled") is False
        ):
            raise ValueError(UNSUPPORTED)
        project = found[1]
        if node_address in project.attachments:
            raise ValueError(UNSUPPORTED)
        project.attachments[node_address] = found[2].removeprefix("serviceAccount:")


def cloud_only_node_addresses(plan: Mapping[str, Any]) -> frozenset[str]:
    """A cloud declaration with no authored guest or substrate demand needs no VM.

    Keep its native node identity for cloud readback. Any OS, image, hardware,
    topology, guest composition or substrate constraint keeps the ordinary
    workload path; no declared guest effect is discarded by this projection.
    """
    result = set()
    nodes = native_cloud_nodes(plan)
    attached = {
        use.get("workload_ref")
        for _address, _name, runtime in nodes
        for authority in runtime.get("identity_authorities", [])
        for use in authority.get("identity_uses", [])
        if use.get("mode") == "attached"
    }
    for address, name, _runtime in nodes:
        if f"nodes.{name}" in attached:
            continue
        payload = plan["resources"][address]["payload"]
        spec = payload["spec"]
        node = spec["node"]
        if any(
            payload.get(key)
            for key in (
                "os_family",
                "os_distribution",
                "os_version",
                "architecture",
                "network_namespace_target",
                "domain_topology",
            )
        ):
            continue
        if payload.get("count") not in (None, 1) or spec.get("infrastructure"):
            continue
        if any(value for key, value in node.items() if key not in {"type", "description", "runtime"}):
            continue
        if any(
            row.get("address") == address and (row.get("posture") != "open" or row.get("value_domain") is not None)
            for row in plan.get("realization_constraints", [])
        ):
            continue
        if any(
            row.get("payload", {}).get("target_address") == address
            for row in plan["resources"].values()
            if row.get("resource_type") != "node"
        ):
            continue
        result.add(address)
    return frozenset(result)


def _audits(authority: dict[str, Any], prefix: str, scopes: dict[str, GcpProjectWork], subjects: SubjectMap) -> None:
    for scope in records(authority.get("resource_scopes", [])):
        target = scopes[f"{prefix}.resource_scopes.{scope['scope_id']}"]
        for audit in records(scope.get("audit_logs", [])):
            supported(audit, {"audit_log_id", "service", "log_type", "exempted_principal_refs"})
            service = token(audit.get("service"), r"(?:allServices|[a-z0-9.-]+\.googleapis\.com)")
            log_type = token(audit.get("log_type"), r"(?:ADMIN_READ|DATA_READ|DATA_WRITE)")
            exemptions = [_principal(ref, subjects) for ref in audit.get("exempted_principal_refs", [])]
            target.audits.append({"service": service, "log_type": log_type, "exempted_members": exemptions})


def _binding_condition(binding: dict[str, Any]) -> dict[str, Any] | None:
    condition = binding.get("condition")
    if condition is not None:
        supported(condition, {"language", "expression"})
        if condition.get("language") not in {"cel", "CEL"} or not isinstance(condition.get("expression"), str):
            raise ValueError(UNSUPPORTED)
        condition = {"title": token(binding.get("binding_id")), "expression": condition["expression"]}
        if binding.get("description"):
            condition["description"] = binding["description"]
    elif binding.get("description"):
        raise ValueError(UNSUPPORTED)
    return condition
