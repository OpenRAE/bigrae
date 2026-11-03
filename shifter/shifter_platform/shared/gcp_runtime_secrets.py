"""Lower native Secret Manager declarations to ephemeral provider arguments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.gcp_runtime_types import UNSUPPORTED, GcpProjectWork, TargetMap, records, supported, token


def compile_secret_application(
    application: dict[str, Any],
    node_name: str,
    scopes: dict[str, GcpProjectWork],
    contents: Mapping[str, bytes],
    targets: TargetMap,
) -> None:
    """Admit literal Secret Manager resources and payloads before provider work."""
    supported(
        application,
        {"platform_application_id", "product", "resource_scope_ref", "secrets"},
        {
            "service": "",
            "platform_kind": "unknown",
            "version": "",
            "name": "",
            "capabilities": [],
            "organizations": [],
            "tenants": [],
            "content_objects": [],
            "markings": [],
            "upstream_bindings": [],
            "connectors": [],
            "execution_policy": None,
            "settings": [],
            "authorization_ref": "",
            "cloud_limits": [],
            "description": "",
        },
    )
    if application.get("product") != "GCP Secret Manager":
        raise ValueError(UNSUPPORTED)
    prefix = f"nodes.{node_name}.runtime.platform_applications.{token(application.get('platform_application_id'))}"
    for secret in records(application.get("secrets", [])):
        supported(
            secret,
            {"secret_id", "native_id", "resource_scope_ref", "replication", "versions"},
            {
                "consumers": [],
                "location": "",
                "replica_locations": [],
                "encryption_key_ref": "",
                "reset_owner_ref": "",
                "deletion_owner_ref": "",
                "description": "",
            },
        )
        project = scopes.get(secret.get("resource_scope_ref") or application.get("resource_scope_ref", ""))
        if project is None:
            raise ValueError(UNSUPPORTED)
        name = token(secret.get("native_id"), r"[A-Za-z0-9_-]{1,255}")
        if name in project.secrets:
            raise ValueError(UNSUPPORTED)
        provider_replication = _replication(secret.get("replication"))
        versions = []
        for version in records(secret.get("versions", [])):
            supported(
                version,
                {"version_id", "native_id", "state", "native_state", "payload_content_ref"},
                {"description": ""},
            )
            version_ref = f"{prefix}.secrets.{secret['secret_id']}.versions.{version['version_id']}"
            payload = contents.get(version.get("payload_content_ref") or version_ref)
            if not isinstance(payload, bytes) or not 0 <= len(payload) <= 65536 or version.get("state") != "enabled":
                raise ValueError(UNSUPPORTED)
            if version.get("native_id") or version.get("native_state", "") not in {"", str(version["state"]).upper()}:
                raise ValueError(UNSUPPORTED)
            versions.append(
                {
                    "version_id": token(version.get("version_id")),
                    "enabled": version["state"] == "enabled",
                    "payload": payload,
                }
            )
        project.secrets[name] = {"replication": provider_replication, "versions": versions}
        targets[f"{prefix}.secrets.{token(secret.get('secret_id'))}"] = (project, "secret", name)


def _replication(replication: object) -> dict[str, Any]:
    if not isinstance(replication, dict):
        raise ValueError(UNSUPPORTED)
    supported(replication, {"provider", "mode", "replicas", "kms_key_name"})
    if replication.get("provider") != "gcp-secret-manager" or replication.get("kms_key_name"):
        raise ValueError(UNSUPPORTED)
    provider_replication: dict[str, Any]
    if replication.get("mode") == "automatic" and not replication.get("replicas"):
        provider_replication = {"auto": {}}
    elif replication.get("mode") == "user-managed":
        replicas = records(replication.get("replicas"))
        if not replicas:
            raise ValueError(UNSUPPORTED)
        provider_replication = {"user_managed": {"replicas": []}}
        for replica in replicas:
            supported(replica, {"location"}, {"kms_key_name": None})
            provider_replication["user_managed"]["replicas"].append(
                {"location": token(replica.get("location"), r"[a-z][a-z0-9-]{1,62}")}
            )
    else:
        raise ValueError(UNSUPPORTED)
    return provider_replication
