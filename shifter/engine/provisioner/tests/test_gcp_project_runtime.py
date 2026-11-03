"""Exercise native provider definitions against an independently mutable synthetic project."""

import base64
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from shared.gcp_range_projects import GcpProjectBaseline, GcpSecretState, GcpServiceAccountState
from shared.gcp_runtime_plan import GcpProjectWork

import gcp_project_runtime as runtime
from gcp_project_readback import verify_project_setup
from gcp_project_terraform import terraform_document
from tests.test_gcp_project_baselines import capture as capture
from tests.test_gcp_project_baselines import lease
from tests.test_gcp_project_baselines import run as capture_baseline


class Inventory:
    def __init__(self, provider):
        self.provider = provider

    def read(self, project_id):
        assert project_id == self.provider.held.project_id
        return self.provider.current.model_copy(deep=True)

    def read_owned_payload(self, number, version, owned_secrets):
        assert number == self.provider.held.project_number and version.split("/")[3] in owned_secrets
        return self.provider.payloads[version]

    def restore_policy(self, number, policy, current):
        assert number == self.provider.held.project_number and current["etag"] == self.provider.current.policy["etag"]
        self.provider.calls.append("restore-policy")
        self.provider.current.policy.clear()
        self.provider.current.policy.update(deepcopy(policy))
        self.provider.current.policy["etag"] = "restored"


class Terraform:
    def __init__(self, selected, document, provider):
        self.provider = provider
        self.work, self.document = selected, document
        self.state = self.provider.states.setdefault(selected.lease.lease_id, {})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def save(self, kind, key, values):
        address = f"{kind}.{key}"
        self.state[address] = {
            "address": address,
            "type": kind,
            "mode": "managed",
            "provider_name": "registry.terraform.io/hashicorp/google",
            "values": values,
        }

    def resolve(self, value):
        if isinstance(value, str) and value.startswith("serviceAccount:${"):
            resource = value.removeprefix("serviceAccount:${").removesuffix(".email}")
            return "serviceAccount:" + self.state[resource]["values"]["email"]
        if isinstance(value, str) and value.startswith("${"):
            resource, attribute = value[2:-1].rsplit(".", 1)
            return self.state[resource]["values"][attribute]
        return value

    def run(self, command, *args):
        self.provider.calls.append(command)
        if command == "show":
            return {"values": {"root_module": {"resources": deepcopy(list(self.state.values()))}}}
        if command == "apply":
            self.apply()
        elif command == "destroy":
            self.destroy()
        else:
            raise AssertionError(command)
        return None

    def apply(self):
        for key, row in self.document["resource"].get("google_service_account", {}).items():
            self.provider.counter += 1
            email = row["account_id"] + "@" + row["project"] + ".iam.gserviceaccount.com"
            name = f"projects/{row['project']}/serviceAccounts/{email}"
            self.provider.current.service_accounts[email] = GcpServiceAccountState(
                resource={
                    "name": name,
                    "projectId": row["project"],
                    "email": email,
                    "uniqueId": str(self.provider.counter),
                    "displayName": row["display_name"],
                    "description": row["description"],
                    "disabled": row["disabled"],
                },
                policy={"etag": "new"},
            )
            self.save(
                "google_service_account",
                key,
                {**row, "email": email, "name": name, "id": name, "unique_id": str(self.provider.counter)},
            )
        for key, row in self.document["resource"].get("google_secret_manager_secret", {}).items():
            name = f"projects/{self.provider.held.project_number}/secrets/{row['secret_id']}"
            self.provider.current.secrets[name] = GcpSecretState(
                resource={"name": name, "createTime": "created-now", "replication": {"automatic": {}}},
                policy={"etag": "new"},
            )
            self.save(
                "google_secret_manager_secret", key, {**row, "id": name, "name": name, "create_time": "created-now"}
            )
        for key, row in self.document["resource"].get("google_secret_manager_secret_version", {}).items():
            secret = self.resolve(row["secret"])
            name = secret + "/versions/1"
            self.provider.current.secrets[secret].versions[name] = {"name": name, "state": "ENABLED"}
            self.provider.payloads[name] = base64.b64decode(row["secret_data"])
            self.save(
                "google_secret_manager_secret_version",
                key,
                {**row, "project": self.provider.held.project_id, "secret": secret, "name": name, "id": name},
            )
        for kind in ("google_project_iam_member", "google_secret_manager_secret_iam_member"):
            for key, row in self.document["resource"].get(kind, {}).items():
                # Creation/destruction must depend on every owned account.
                assert set(row["depends_on"]) >= {
                    address for address in self.state if address.startswith("google_service_account.")
                }
                values = {field: self.resolve(value) for field, value in row.items()}
                policy = (
                    self.provider.current.policy
                    if kind == "google_project_iam_member"
                    else self.provider.current.secrets[
                        f"projects/{self.provider.held.project_number}/secrets/{values['secret_id']}"
                    ].policy
                )
                policy.setdefault("bindings", []).append({"role": values["role"], "members": [values["member"]]})
                self.save(kind, key, values)
        for key, row in self.document["resource"].get("google_project_iam_audit_config", {}).items():
            self.provider.current.policy["auditConfigs"] = [
                {
                    "service": row["service"],
                    "auditLogConfigs": [
                        {
                            "logType": item["log_type"],
                            **({"exemptedMembers": item["exempted_members"]} if item["exempted_members"] else {}),
                        }
                        for item in row["audit_log_config"]
                    ],
                }
            ]
            self.save("google_project_iam_audit_config", key, row)

    def destroy(self):
        for row in list(self.state.values()):
            kind, values = row["type"], row["values"]
            if kind.endswith("_iam_member"):
                policy = (
                    self.provider.current.policy
                    if kind == "google_project_iam_member"
                    else self.provider.current.secrets[
                        f"projects/{self.provider.held.project_number}/secrets/{values['secret_id']}"
                    ].policy
                )
                policy["bindings"] = [
                    item
                    for item in policy.get("bindings", [])
                    if not (item["role"] == values["role"] and values["member"] in item["members"])
                ]
        self.provider.current.policy["auditConfigs"] = []
        self.provider.current.secrets.clear()
        self.provider.payloads.clear()
        for email in list(self.provider.current.service_accounts):
            assert all(
                "serviceAccount:" + email not in row.get("members", [])
                for row in self.provider.current.policy["bindings"]
            )
            del self.provider.current.service_accounts[email]
        self.state.clear()


@pytest.fixture
def project(capture, monkeypatch):
    receipt = capture_baseline(capture)
    held = lease(capture, receipt)
    original = capture[2].read.return_value.model_copy(deep=True)
    original.policy.update(
        {
            "version": 3,
            "etag": "baseline",
            "bindings": [
                {"role": "roles/owner", "members": ["serviceAccount:manager@synthetic-control.iam.gserviceaccount.com"]}
            ],
            "auditConfigs": [
                {"service": "secretmanager.googleapis.com", "auditLogConfigs": [{"logType": "ADMIN_READ"}]}
            ],
        }
    )
    reference = held.baseline.model_copy(update={"state_digest": original.digest})
    held = held.model_copy(update={"baseline": reference})
    baseline = GcpProjectBaseline(
        schema_version="bigrae.gcp-project-baseline/v1",
        registration_id=reference.registration_id,
        capture_operation_id=reference.capture_operation_id,
        organization_uuid=held.organization_uuid,
        project_id=held.project_id,
        project_number=held.project_number,
        captured_at=datetime.now(UTC),
        state=original,
    )
    email = "reader-sa@synthetic-project.iam.gserviceaccount.com"
    work = GcpProjectWork(
        held,
        accounts={
            email: {
                "account_id": "reader-sa",
                "display_name": "Exact display name",
                "description": "Exact description",
                "disabled": False,
            }
        },
        secrets={
            "example": {
                "replication": {"auto": {}},
                "versions": [{"version_id": "v1", "enabled": True, "payload": b"literal-value\n"}],
            }
        },
        grants=[
            {
                "kind": "secret",
                "target": "example",
                "role": "roles/secretmanager.secretAccessor",
                "member": "serviceAccount:" + email,
                "condition": None,
            },
            {
                "kind": "project",
                "target": held.project_id,
                "role": "roles/viewer",
                "member": "serviceAccount:" + email,
                "condition": None,
            },
        ],
        audits=[{"service": "secretmanager.googleapis.com", "log_type": "DATA_READ", "exempted_members": []}],
    )
    provider = SimpleNamespace(
        held=held, current=original.model_copy(deep=True), counter=100, payloads={}, states={}, calls=[]
    )

    monkeypatch.setattr(runtime, "ProjectTerraform", lambda selected, document: Terraform(selected, document, provider))
    return SimpleNamespace(
        work=work,
        baseline=baseline,
        provider=provider,
        inventory=Inventory(provider),
        email=email,
        make=lambda selected: runtime.RegisteredProjectRuntime(
            ((selected, baseline, terraform_document(selected, baseline)),), Inventory(provider)
        ),
    )


def test_two_cycles_restore_baseline_and_regrant_to_new_account_incarnation(project):
    observed_ids = []
    for _ in range(2):
        context = project.make(project.work)
        observed = context.provision()
        observed_ids.append(
            observed[project.work.lease.project_id].service_accounts[project.email].resource["uniqueId"]
        )
        assert context.completion(observed)[0]["lease_id"] == str(project.work.lease.lease_id)
        proofs = context.destroy()
        assert proofs[0]["observed_state_digest"] == project.baseline.state.digest
        assert project.provider.current.digest == project.baseline.state.digest
        project.work.lease = project.work.lease.model_copy(update={"lease_id": uuid4(), "source_operation_id": uuid4()})
    assert observed_ids[0] != observed_ids[1]


@pytest.mark.parametrize("change", ["account-incarnation", "secret-incarnation"])
def test_recreated_name_does_not_authorize_deleting_another_incarnation(project, change):
    context = project.make(project.work)
    context.provision()
    if change == "account-incarnation":
        project.provider.current.service_accounts[project.email].resource["uniqueId"] = "different"
    else:
        project.provider.current.secrets[f"projects/{project.work.lease.project_number}/secrets/example"].resource[
            "createTime"
        ] = "different"
    before = project.provider.calls.count("destroy")
    with pytest.raises(ValueError, match="readback"):
        context.destroy()
    assert project.provider.calls.count("destroy") == before


@pytest.mark.parametrize("change", ["payload", "extra-grant", "missing-account", "display-name"])
def test_independent_readback_catches_provider_differences(project, change):
    context = project.make(project.work)
    observed = context.provision()
    actual = observed[project.work.lease.project_id]
    if change == "payload":
        project.provider.payloads[next(iter(project.provider.payloads))] = b"wrong"
    elif change == "extra-grant":
        actual.policy["bindings"].append({"role": "roles/editor", "members": ["allUsers"]})
    elif change == "missing-account":
        actual.service_accounts.clear()
    else:
        actual.service_accounts[project.email].resource["displayName"] = "different"
    state = {
        "values": {"root_module": {"resources": list(project.provider.states[project.work.lease.lease_id].values())}}
    }
    with pytest.raises(ValueError):
        verify_project_setup(
            project.work, project.baseline, actual, state, lambda name: project.provider.payloads[name]
        )
