"""Keep native project realization on the existing range lifecycle path."""

from __future__ import annotations

from typing import Any, Protocol, cast

from shared.gcp_range_projects import GcpProjectRestorationProof, GcpProjectState

from config import GCERangeCellConfig
from gcp_project_runtime import RegisteredProjectRuntime, prepare_registered_projects
from provisioner_db_operation_input import RaesOperationRun
from raes_plan import RaesPlan, RaesPlanError, parse_plan


def prepare_cloud_plan(
    original: RaesOperationRun, effective: RaesOperationRun, *, cleanup_only: bool = False
) -> tuple[RaesPlan, RegisteredProjectRuntime | None]:
    """The unimplemented-family barrier opens only after complete graph/baseline admission."""
    try:
        cloud = prepare_registered_projects(original, effective)
    except ValueError:
        raise RaesPlanError("native cloud runtime declaration is unsupported or unavailable") from None
    return parse_plan(effective.input.plan, cleanup_only=cleanup_only, cloud_admitted=cloud is not None), cloud


def realize_cloud_projects(
    cloud: RegisteredProjectRuntime | None, config: GCERangeCellConfig, enrollment: object | None
) -> dict[str, GcpProjectState]:
    """Do not repurpose VM infrastructure or silently replace a model identity."""
    if cloud is None:
        return {}
    if any(work.lease.project_id == config.project_id for work, _baseline, _document in cloud.projects):
        raise ValueError("A workload infrastructure project cannot be a scenario project")
    if enrollment is not None and cloud.attachments:
        raise ValueError("Combined model and scenario workload identities are unsupported")
    return cloud.provision()


class _Instance(Protocol):
    service_accounts: list[Any]


def cloud_completion(
    cloud: RegisteredProjectRuntime | None,
    observed: dict[str, GcpProjectState],
    config: GCERangeCellConfig | None,
    instances: object,
) -> list[dict[str, Any]] | None:
    """Read the actual VM account attachment before claiming declared identity use."""
    if cloud is None:
        return None
    expected = cloud.attachments
    if expected:
        from gcp_range_cell_clients import _build_clients

        if not isinstance(instances, list) or config is None:
            raise ValueError("Workload identity readback is unavailable")
        clients = _build_clients()
        seen = set()
        for row in instances:
            address = str(row.get("uuid", "")).rpartition("#")[0]
            if address not in expected:
                continue
            actual = cast(
                _Instance,
                clients.instances.get(project=config.project_id, zone=config.zone, instance=row["gcp_instance_name"]),
            )
            accounts = [account.email for account in actual.service_accounts]
            if accounts != [expected[address]]:
                raise ValueError("Workload identity does not match the declared account")
            seen.add(address)
        if seen != set(expected):
            raise ValueError("Workload identity readback is incomplete")
    return cloud.completion(observed)


def restore_cloud_projects(cloud: RegisteredProjectRuntime | None, inventory: dict[str, Any]) -> dict[str, Any]:
    """A VM-only absence proof cannot release cloud project custody."""
    if cloud is None or inventory.get("outcome") != "VERIFIED_ABSENT" or inventory.get("residual_categories"):
        return inventory
    try:
        proofs = cloud.destroy()
    except Exception:  # noqa: BLE001  # preserve closed cleanup evidence without provider diagnostics
        proofs = [
            GcpProjectRestorationProof(
                lease_id=work.lease.lease_id,
                registration_id=work.lease.baseline.registration_id,
                baseline_state_digest=work.lease.baseline.state_digest,
                outcome="incomplete",
                failure_code="readback-unavailable",
            ).model_dump(mode="json")
            for work, _baseline, _document in cloud.projects
        ]
        return {
            "outcome": "INCOMPLETE",
            "residual_categories": ["cloud-projects"],
            "scope": {**inventory.get("scope", {}), "gcp_projects": proofs},
        }
    return {**inventory, "scope": {**inventory.get("scope", {}), "gcp_projects": proofs}}
