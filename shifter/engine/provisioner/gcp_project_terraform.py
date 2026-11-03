"""Realize validated native project intent using the existing Terraform toolchain."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from shared.gcp_range_projects import GcpProjectBaseline
from shared.gcp_runtime_plan import GcpProjectWork
from shifter_adapter_sdk.runtime import canonical_digest

_FAILED = "Registered project realization failed"
_MODULE = Path(__file__).parent / "terraform/modules/registered-gcp-project"


def resource_key(identity: str) -> str:
    """Stable Terraform labels contain no authored names or executable syntax."""
    return "r_" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def literal[T](value: T) -> T:
    """Keep authored template-looking text literal in Terraform JSON strings."""
    if isinstance(value, str):
        return cast(T, value.replace("${", "$${").replace("%{", "%%{"))
    result: object = value
    if isinstance(value, list):
        result = [literal(item) for item in value]
    elif isinstance(value, dict):
        result = {key: literal(item) for key, item in value.items()}
    return cast(T, result)


def terraform_document(work: GcpProjectWork, baseline: GcpProjectBaseline) -> dict[str, Any]:
    """Generate data-only resources; never import or execute a pack's Terraform."""
    baseline.authorize(work.lease)
    _require_new_names(work, baseline)
    resources: dict[str, dict[str, Any]] = defaultdict(dict)
    project = work.lease.project_id
    accounts = resources["google_service_account"]
    for email, account in work.accounts.items():
        accounts[resource_key(email)] = {"project": project, **literal(account)}
    account_dependencies = [f"google_service_account.{key}" for key in accounts]
    _secret_resources(resources, work)
    for grant in work.grants:
        if _baseline_grant(baseline, grant):
            continue
        kind = grant["kind"]
        member = literal(grant["member"])
        # Terraform's resource references impose both creation and reverse
        # destruction order, including grants on another owned resource.
        dependencies = list(account_dependencies)
        if grant["member"].startswith("serviceAccount:") and grant["member"][15:] in work.accounts:
            member = "serviceAccount:${google_service_account." + resource_key(grant["member"][15:]) + ".email}"
        body = {"role": literal(grant["role"]), "member": member, "depends_on": dependencies}
        if grant["condition"] is not None:
            body["condition"] = literal(grant["condition"])
        if kind == "project":
            resource_type = "google_project_iam_member"
            body["project"] = project
        elif kind == "service-account":
            resource_type = "google_service_account_iam_member"
            body["service_account_id"] = "${google_service_account." + resource_key(grant["target"]) + ".name}"
        else:
            resource_type = "google_secret_manager_secret_iam_member"
            body["project"] = project
            body["secret_id"] = "${google_secret_manager_secret." + resource_key(grant["target"]) + ".secret_id}"
        key = resource_key(canonical_digest(grant))
        if key in resources[resource_type]:
            raise ValueError(_FAILED)
        resources[resource_type][key] = body
    _audit_resources(resources, work, baseline)
    return {
        "provider": {"google": {"project": project, "add_terraform_attribution_label": False}},
        "resource": {kind: values for kind, values in resources.items() if values},
    }


def _baseline_grant(baseline: GcpProjectBaseline, grant: dict[str, Any]) -> bool:
    """An already-existing baseline grant must never become range-owned state."""
    if grant["kind"] != "project":
        return False
    policy: dict[str, Any] = baseline.state.policy
    for row in policy.get("bindings", []):
        if (
            isinstance(row, dict)
            and (row.get("role"), row.get("condition")) == (grant["role"], grant["condition"])
            and grant["member"] in row.get("members", [])
        ):
            return True
    return False


def _audit_resources(resources: dict[str, dict[str, Any]], work: GcpProjectWork, baseline: GcpProjectBaseline) -> None:
    policy: dict[str, Any] = baseline.state.policy
    services = {audit["service"] for audit in work.audits}
    for service in sorted(services):
        rows: dict[str, set[str]] = {}
        for config in policy.get("auditConfigs", []):
            if config.get("service") == service:
                for row in config.get("auditLogConfigs", []):
                    rows[row["logType"]] = set(row.get("exemptedMembers", []))
        for audit in work.audits:
            if audit["service"] == service:
                rows.setdefault(audit["log_type"], set()).update(audit["exempted_members"])
        resources["google_project_iam_audit_config"][resource_key(service)] = {
            "project": work.lease.project_id,
            "service": service,
            "audit_log_config": [
                {"log_type": log_type, "exempted_members": sorted(members)}
                for log_type, members in sorted(rows.items())
            ],
        }


class ProjectTerraform:
    """One private workspace backed by the existing bucket's lease-specific state."""

    def __init__(self, work: GcpProjectWork, document: dict[str, Any]) -> None:
        self.work, self.document = work, document
        self._workspace: TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> ProjectTerraform:
        self._workspace = TemporaryDirectory(prefix="registered-project-")
        self.path = Path(self._workspace.name)
        try:
            self._initialize()
        except Exception:  # noqa: BLE001  # remove private workspace and suppress provider/config diagnostics
            self._workspace.cleanup()
            raise ValueError(_FAILED) from None
        return self

    def _initialize(self) -> None:
        if self.path is None:
            raise ValueError(_FAILED)
        for name in ("versions.tf", ".terraform.lock.hcl"):
            shutil.copyfile(_MODULE / name, self.path / name)
        self._write("main.tf.json", self.document)
        # CSEK protects secret-bearing Terraform state with the already-used
        # application key; no new key service or state bucket is introduced.
        key = base64.urlsafe_b64decode(os.environ["FIELD_ENCRYPTION_KEY"].encode())
        if len(key) != 32:
            raise ValueError(_FAILED)
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"bigrae/gcp-project-state/v1/" + self.work.lease.lease_id.bytes,
        ).derive(key)
        self._write(
            "backend.json",
            {
                "bucket": self.work.lease.baseline.bucket,
                "prefix": f"raes/project-state/{self.work.lease.lease_id.hex}",
                "encryption_key": base64.b64encode(key).decode("ascii"),
            },
        )
        self.run("init", "-backend-config=backend.json", "-lockfile=readonly")

    def __exit__(self, *args: object) -> None:
        if self._workspace is not None:
            self._workspace.cleanup()

    def _write(self, name: str, value: object) -> None:
        if self.path is None:
            raise ValueError(_FAILED)
        path = self.path / name
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)

    def run(self, command: str, *args: str) -> dict[str, Any] | None:
        """Suppress provider output: errors and state can contain client payloads."""
        if self.path is None or command not in {"init", "apply", "destroy", "show"}:
            raise ValueError(_FAILED)
        argv = ["terraform", command, "-no-color", *args]
        if command in {"apply", "destroy"}:
            argv += ["-input=false", "-auto-approve", "-lock-timeout=60s", "-parallelism=8"]
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"TF_LOG", "TF_LOG_PATH"} and not key.startswith("TF_CLI_ARGS")
        }
        env["TF_IN_AUTOMATION"] = "1"
        try:
            # The directory is mode 0700; provider output never enters task logs.
            with (self.path / "terraform-output.log").open("w+b") as output:
                completed = subprocess.run(  # noqa: S603  # fixed binary/commands, host-owned arguments, no shell
                    argv, cwd=self.path, env=env, stdout=output, stderr=output, timeout=1800, check=False
                )
                if completed.returncode:
                    raise ValueError(_FAILED)
                if command == "show":
                    output.seek(0)
                    if os.fstat(output.fileno()).st_size > 16 * 1024 * 1024:
                        raise ValueError(_FAILED)
                    result = json.load(output)
                    if not isinstance(result, dict):
                        raise ValueError(_FAILED)
                    return result
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError(_FAILED) from None
        return None


def _secret_resources(resources: dict[str, dict[str, Any]], work: GcpProjectWork) -> None:
    """Create each literal version after its owning secret and earlier versions."""
    project = work.lease.project_id
    for name, secret in work.secrets.items():
        key = resource_key(name)
        secret_address = f"google_secret_manager_secret.{key}"
        resources["google_secret_manager_secret"][key] = {
            "project": project,
            "secret_id": name,
            "replication": literal(secret["replication"]),
            "deletion_protection": False,
        }
        previous = secret_address
        for version in secret["versions"]:
            version_key = resource_key(name + "/" + version["version_id"])
            resources["google_secret_manager_secret_version"][version_key] = {
                "secret": "${" + secret_address + ".id}",
                "secret_data": base64.b64encode(version["payload"]).decode("ascii"),
                "is_secret_data_base64": True,  # nosec B105 # provider encoding boolean
                "enabled": version["enabled"],
                "deletion_policy": "DELETE",
                "depends_on": [previous],
            }
            previous = f"google_secret_manager_secret_version.{version_key}"


def _require_new_names(work: GcpProjectWork, baseline: GcpProjectBaseline) -> None:
    """Existing baseline identities never become range-owned Terraform resources."""
    if set(work.accounts) & set(baseline.state.service_accounts):
        raise ValueError(_FAILED)
    names = {name.rsplit("/", 1)[-1] for name in baseline.state.secrets}
    if names & set(work.secrets):
        raise ValueError(_FAILED)
