"""MVP native project lifecycle: Terraform effects, independent readback, exact restoration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial
from typing import Any

from cryptography.fernet import Fernet
from shared.gcp_cloud_content import open_cloud_content
from shared.gcp_project_completion import GcpProjectCompletion, cloud_configuration_digest
from shared.gcp_project_registration import (
    PROTECTED_IMAGE_ENV_NAMES,
    PROTECTED_PROJECT_ENV_NAMES,
    configured_project_ids,
)
from shared.gcp_range_projects import (
    GcpProjectBaseline,
    GcpProjectRestorationProof,
    GcpProjectState,
    require_project_parity,
)
from shared.gcp_runtime_plan import GcpProjectWork, compile_cloud_work
from shifter_adapter_sdk.runtime import canonical_digest

from config._crypto import decrypt_field
from config._gce_image_keys import _load_gce_image_key_profiles
from gcp_project_baselines import GcsBaselineStore, load_project_baseline
from gcp_project_inventory import GcpProjectInventory
from gcp_project_readback import (
    require_recorded_incarnations,
    terraform_resources,
    verify_policy_after_destroy,
    verify_project_setup,
)
from gcp_project_terraform import ProjectTerraform, terraform_document
from provisioner_db_operation_input import RaesOperationRun


@dataclass
class RegisteredProjectRuntime:
    """All plan and baseline admission finishes before the first project is mutated."""

    projects: tuple[tuple[GcpProjectWork, GcpProjectBaseline, dict[str, Any]], ...]
    inventory: GcpProjectInventory

    def completion(self, observed: dict[str, GcpProjectState]) -> list[dict[str, Any]]:
        """Issue proofs only from the provider inventory that passed parity/readback."""
        if set(observed) != {work.lease.project_id for work, _baseline, _document in self.projects}:
            raise ValueError("Registered project completion is incomplete")
        return [
            GcpProjectCompletion(
                lease_id=work.lease.lease_id,
                project_id=work.lease.project_id,
                configuration_digest=cloud_configuration_digest(work),
                observed_state_digest=observed[work.lease.project_id].digest,
            ).model_dump(mode="json")
            for work, _baseline, _document in self.projects
        ]

    @property
    def attachments(self) -> dict[str, str]:
        """One explicit account per workload, independent of private scenario names."""
        pairs = [(address, email) for work, _base, _doc in self.projects for address, email in work.attachments.items()]
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Workload identity is ambiguous")
        return result

    def _read(self, work: GcpProjectWork) -> GcpProjectState:
        current = self.inventory.read(work.lease.project_id)
        if (
            current.project.get("name") != f"projects/{work.lease.project_number}"
            or current.project.get("projectId") != work.lease.project_id
        ):
            raise ValueError("Registered project identity changed")
        return current

    def provision(self) -> dict[str, GcpProjectState]:
        """Apply the admitted resources; do not present requested state as readback."""
        result = {}
        for work, baseline, document in self.projects:
            with ProjectTerraform(work, document) as terraform:
                current = self._read(work)
                state = terraform.run("show", "-json") or {}
                if not terraform_resources(state):
                    require_project_parity(baseline.state, current)
                else:
                    require_recorded_incarnations(work, current, state, document)
                # Terraform resumes its own partial state; BigRAE adds no
                # separate recovery engine or ownership inference.
                terraform.run("apply")
                state = terraform.run("show", "-json") or {}
                current = self._read(work)
                verify_project_setup(
                    work,
                    baseline,
                    current,
                    state,
                    partial(
                        self.inventory.read_owned_payload, work.lease.project_number, owned_secrets=set(work.secrets)
                    ),
                )
                result[work.lease.project_id] = current
        return result

    def destroy(self) -> list[dict[str, Any]]:
        """Delete only state-owned incarnations, restore the policy, and verify the baseline."""
        proofs = []
        for work, baseline, document in self.projects:
            with ProjectTerraform(work, document) as terraform:
                current = self._read(work)
                state = terraform.run("show", "-json") or {}
                if terraform_resources(state):
                    require_recorded_incarnations(work, current, state, document)
                    terraform.run("destroy")
                    current = self._read(work)
                try:
                    require_project_parity(baseline.state, current)
                except ValueError:
                    verify_policy_after_destroy(work, baseline, current)
                    self.inventory.restore_policy(work.lease.project_number, baseline.state.policy, current.policy)
                    current = self._read(work)
                require_project_parity(baseline.state, current)
                proofs.append(
                    GcpProjectRestorationProof(
                        lease_id=work.lease.lease_id,
                        registration_id=work.lease.baseline.registration_id,
                        baseline_state_digest=work.lease.baseline.state_digest,
                        observed_state_digest=current.digest,
                        outcome="restored",
                    ).model_dump(mode="json")
                )
        return proofs


def prepare_registered_projects(
    original: RaesOperationRun, effective: RaesOperationRun
) -> RegisteredProjectRuntime | None:
    """Use original sealed content and the already-approved effective native plan."""
    contents = open_cloud_content(original.input.cloud_content, original.input.plan, decrypt_field)
    contents.update(effective.input.secret_payloads)
    work = compile_cloud_work(effective.input.plan, effective.input.gcp_projects, contents)
    if not work:
        return None
    if effective.input.range_backend != "gce":
        raise ValueError("Native cloud realization requires the GCE backend")
    images = [os.environ.get(name, "") for name in PROTECTED_IMAGE_ENV_NAMES]
    images.extend(
        profile.source_image or profile.source_machine_image
        for entries in _load_gce_image_key_profiles().values()
        for profile in entries.values()
    )
    protected = configured_project_ids((os.environ.get(name, "") for name in PROTECTED_PROJECT_ENV_NAMES), images)
    for project in work:
        project.lease.authorize(
            request_id=project.lease.request_id,
            range_id=original.input.legacy_range_id,
            plan_digest=canonical_digest(original.input.plan),
        )
        if str(project.lease.request_id) != original.request_id or project.lease.project_id in protected:
            raise ValueError("Registered project is unavailable")
    store, cipher = GcsBaselineStore(), Fernet(os.environ["FIELD_ENCRYPTION_KEY"].encode())
    baselines = [load_project_baseline(project.lease, store=store, cipher=cipher) for project in work]
    projects = tuple(
        (project, baseline, terraform_document(project, baseline))
        for project, baseline in zip(work, baselines, strict=True)
    )
    runtime = RegisteredProjectRuntime(projects, GcpProjectInventory())
    _ = runtime.attachments  # Validate cross-project duplicate workload claims before effects.
    return runtime
