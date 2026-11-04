"""Admit configuration-bound provider readback through native value-free disclosures."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from raes_contracts.planning import ProvisioningPlan
from raes_contracts.runtime_state import RealizationObservationDisclosure, RuntimeSnapshot
from raes_contracts.vocabulary import ObservationStrength, RealizationVerificationScope

from shared.gcp_project_completion import GcpProjectCompletion, cloud_configuration_digest
from shared.gcp_runtime_plan import native_cloud_nodes
from shared.gcp_runtime_types import GcpProjectWork


def admit_cloud_completion(
    plan: ProvisioningPlan,
    serialized: Mapping[str, Any],
    evidence: dict[str, Any],
    snapshot: RuntimeSnapshot,
    context: tuple[dict[str, Any], tuple[GcpProjectWork, ...]] | None,
) -> None:
    """Native configuration is corroborated only after complete provider parity.

    This follows composition readback: the worker supplies a proof bound to
    the admitted configuration, not a copy of requested arrays as observations.
    The host alone reconstructs accepted preparation and owns native admission.
    """
    nodes = native_cloud_nodes(serialized)
    supplied = evidence.get("cloud_projects", [])
    if not nodes:
        if supplied:
            raise ValueError("Unexpected cloud completion")
        return
    if context is None:
        raise ValueError("Cloud completion requires its retained execution context")
    effective, work = context
    proofs = [GcpProjectCompletion.model_validate(row) for row in supplied]
    by_lease = {row.lease_id: row for row in proofs}
    if len(by_lease) != len(proofs) or set(by_lease) != {row.lease.lease_id for row in work}:
        raise ValueError("Cloud completion project coverage is incomplete")
    for project in work:
        proof = by_lease[project.lease.lease_id]
        if proof.project_id != project.lease.project_id or proof.configuration_digest != cloud_configuration_digest(
            project
        ):
            raise ValueError("Cloud completion belongs to another configuration")
    _corroborate_runtime(plan, effective, snapshot)


def _corroborate_runtime(plan: ProvisioningPlan, effective: dict[str, Any], snapshot: RuntimeSnapshot) -> None:
    """Project accepted native configuration only after all bound proofs passed."""
    observations = list(snapshot.realization_observations)
    for address, _name, runtime in native_cloud_nodes(effective):
        payload = snapshot.entries[address].payload
        for field, kind in (
            ("identity_authorities", "runtime-identity-authorities"),
            ("platform_applications", "runtime-platform-applications"),
        ):
            if not runtime.get(field):
                continue
            authority = [
                row for row in plan.realization_authority if row.address == address and row.requirement_kind == kind
            ]
            if len(authority) != 1:
                raise ValueError("Cloud completion concern authority is unavailable")
            payload["spec"]["node"]["runtime"][field] = deepcopy(runtime[field])
            observations.append(
                RealizationObservationDisclosure(
                    address=address,
                    field_path=authority[0].field_path,
                    domain="runtime-realization",
                    requirement_kind=kind,
                    verification_scope=RealizationVerificationScope.CONFIGURATION,
                    observation_strength=ObservationStrength.DAEMON_OBSERVED,
                )
            )
    snapshot.realization_observations = tuple(observations)
