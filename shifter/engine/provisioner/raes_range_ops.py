"""Realize admitted RAES ranges and publish bounded native results (ADR-043).

Engine owns custody and authorization; cleanup reports exact provider absence.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from shared.gcp_range_projects import GcpProjectState
from shared.operation_results import MAX_DIAGNOSTIC_CHARS, ResultStep
from shared.raes.completion_evidence import build_completion_evidence
from shared.raes.operation_input import RaesOperationInput

from config import GCERangeCellConfig, load_gce_range_cell_config
from provisioner_db_appends import OperationRef, append_operation_step_result
from provisioner_db_operation_input import (
    RaesOperationRun,
    get_activation_operation_input,
    get_raes_operation_input,
)
from raes_gce_image import registry_image_resolver
from raes_gcp_apply import RaesGceApplyOptions, RaesGceDestroyOptions, apply_raes_range_cell, destroy_raes_range_cell
from raes_gcp_inventory import VERIFIED_ABSENT, inventory_raes_range_cell
from raes_gcp_network_allocation import (
    GceNetworkAllocation,
    RaesRealizationError,
)
from raes_gcp_network_allocation import (
    allocated_networks_for_destroy as _allocated_networks_for_destroy,
)
from raes_gcp_network_allocation import (
    allocated_networks_for_provision as _allocated_networks_for_provision,
)
from raes_openvpn import (
    cleanup_failed_provision_openvpn,
    cleanup_raes_openvpn,
    prepare_raes_openvpn,
    vpn_access_fragment,
    vpn_access_names,
)
from raes_plan import RaesPlan, parse_plan
from raes_range_cloud import cloud_completion, prepare_cloud_plan, realize_cloud_projects, restore_cloud_projects
from raes_range_contract import _classify_failure, _require_gce_live_fire_binding, verified_composition_addresses
from raes_range_members import realized_members as _realized_members
from raes_snapshot import snapshot_resources
from range_placement import resolve_range_cell_placement
from range_subnet_allocation import _release_subnet_allocations_best_effort
from runtime_plugin_preparation import cleanup_preparation
from worker_host_observation import worker_observations_fragment

if TYPE_CHECKING:
    from gcp_project_runtime import RegisteredProjectRuntime
    from runtime_plugin_execution import GuestPluginPlans

logger = logging.getLogger(__name__)

#: The single closed failure code an RAES realization/teardown failure reports.
#: The bounded diagnostic rides the result payload; only this code reaches the
#: range's user-visible error text (ADR-043-R5).
_FAILURE_REASON_CODE = "cloud_operation_failed"

#: Reported when this generation's immutable input cannot be read or validated.
_INPUT_REASON_CODE = "dependency_unavailable"

_RESOURCE = "raes-range"


class RaesGenerationError(RuntimeError):
    """An RAES operation was invoked without its canonical operation generation."""


def _config_for_range_placement(request_id: str, config: GCERangeCellConfig) -> GCERangeCellConfig:
    """Bind ``config`` to this range's realized zone before any plan/cloud work.

    The RAES lifecycle boundary is the symmetric counterpart of the legacy
    ``gcp_range_cells`` binding: it reads the zone chosen at range creation and
    stored on the row, so provision and destroy target the exact same zone and
    teardown never recomputes against a pool that may have changed. An empty stored
    zone returns the config unchanged, preserving single-region behaviour.
    """
    return resolve_range_cell_placement(request_id, config)


def _require_generation(request_id: str, operation_id: str | None, operation: str) -> tuple[OperationRef, str]:
    """Require the immutable input generation before any effect or result publication."""
    if not operation_id:
        raise RaesGenerationError(
            f"raes-range {operation} requires a canonical operation id; refusing to mutate cloud state without one"
        )
    return OperationRef(request_id=request_id, operation_id=operation_id), operation_id


def _report(ref: OperationRef, operation: str, step: ResultStep, payload: dict[str, Any]) -> None:
    """Append one closed result for this operation generation."""
    append_operation_step_result(ref, resource=_RESOURCE, operation=operation, step=step, result_payload=payload)


def _report_failure(
    ref: OperationRef, operation: str, diagnostic: str, reason_code: str = _FAILURE_REASON_CODE
) -> None:
    """Report terminal failure with a closed reason code and bounded diagnostic."""
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": reason_code, "diagnostic": diagnostic[:MAX_DIAGNOSTIC_CHARS]},
    )


def _load_input(ref: OperationRef, operation_id: str, operation: str, request_id: str) -> RaesOperationRun:
    """Validate input or report a bounded failure before effects; Engine fences the provisional ref."""
    try:
        run = get_raes_operation_input(operation_id, request_id=request_id, operation=operation)
        if operation == "provision" and run.input.management_targets and run.input.range_backend != "gce":
            raise ValueError("Worker host observation backend is unsupported")
        return run
    except Exception:
        _report_failure(ref, operation, "operation input could not be read or validated", _INPUT_REASON_CODE)
        raise


def run_raes_range_provision(request_id: str, *, operation_id: str | None = None) -> None:
    """Realize the serialized RAES plan for a generation into a real GCE range cell.

    Reports ``running`` -> bounded runtime snapshot -> ``ready`` on the operation
    contract; the Engine applier turns those into range status, RAES sidecar
    evidence, audit, and the ADR-025 notification in one transaction.
    """
    operation = "provision"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    run = _load_input(provisional_ref, generation, operation, request_id)
    # Correlate every result from the identity the input row proved, not from
    # the argv pair that was merely asserted.
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    operation_input = run.input
    range_id = operation_input.legacy_range_id

    logger.info("Starting RAES range provision for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_PROVISION_RUNNING, {"raes_status": "running"})
    network_allocation: GceNetworkAllocation | None = None
    raes_plan: RaesPlan | None = None
    config: GCERangeCellConfig | None = None
    pre_mutation_release_attempted = False
    preparation_ready = False
    try:
        from runtime_plugin_execution import load_prepared_plugin_run

        effective_run, plugin_plans = load_prepared_plugin_run(run)
        operation_input = effective_run.input
        preparation_ready = True
        raes_plan, cloud = prepare_cloud_plan(run, effective_run)
        if operation_input.range_backend == "ec2":
            from raes_ec2_runtime import provision_ec2_run

            if operation_input.remote_access is not None:
                # The EC2 shared pool is #2481; never launch without it silently.
                raise RaesRealizationError("OpenVPN access is not realized by the EC2 range backend")
            apply_result = provision_ec2_run(effective_run, plugin_plans)
        else:
            backend = _require_gce_live_fire_binding(operation_input)
            config = load_gce_range_cell_config(backend=backend)
            config = _config_for_range_placement(request_id, config)
            cloud_observed: dict[str, GcpProjectState] = {}
            selected_config = config

            def realize_cloud_before_guests() -> None:
                """Run admitted cloud work only after the guest driver's complete preflight."""
                cloud_observed.update(realize_cloud_projects(cloud, selected_config))

            network_allocation = _allocated_networks_for_provision(
                request_id,
                generation,
                raes_plan,
                config,
            )
            openvpn = prepare_raes_openvpn(run.request_id, range_id, raes_plan, operation_input.remote_access)

            def release_pre_mutation_allocation() -> None:
                """Release this generation's reservation before provider mutation."""
                nonlocal pre_mutation_release_attempted
                pre_mutation_release_attempted = True
                _release_subnet_allocations_best_effort(request_id, operation_id=generation)

            apply_result = apply_raes_range_cell(
                request_id,
                range_id,
                raes_plan,
                registry_image_resolver(operation_input),
                options=_apply_guest_callbacks(
                    RaesGceApplyOptions(
                        config=config,
                        cloud_service_accounts=cloud.attachments if cloud is not None else None,
                        before_provider_mutation=realize_cloud_before_guests if cloud is not None else None,
                        egress_mode=operation_input.egress_mode,
                        allocated_network_cidrs=network_allocation.require_available(),
                        on_pre_mutation_failure=(
                            release_pre_mutation_allocation if network_allocation.network_cidrs else None
                        ),
                        openvpn=openvpn,
                    ),
                    plugin_plans,
                ),
                delivery_bindings=operation_input.binding_transport(),
                access_bindings=operation_input.access_binding_transport(),
            )
        observations = worker_observations_fragment(apply_result, operation_input.management_targets)
        resources, members, completion = _provision_evidence(
            run,
            cloud,
            cloud_observed if cloud is not None else {},
            config,
            apply_result,
        )
    except Exception as exc:
        _release_failed_provision_allocation(run, raes_plan, config, network_allocation, pre_mutation_release_attempted)
        if preparation_ready:
            cleanup_failed_provision_openvpn(run.request_id, run.input.legacy_range_id, run.input.remote_access)
        reason_code, diagnostic = _classify_failure(exc, "raes range provision")
        logger.error(
            "RAES range provision failed for request_id=%s exc_type=%s", request_id, type(exc).__name__, exc_info=False
        )
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    # The realized member/access projection rides the terminal result itself, so
    # the Engine validates it and transitions READY in one transaction against
    # this generation's own state (#1710, ADR-032-R10). So does the owner-free
    # OpenVPN realization, which the Engine binds to the range owner (#2030).
    _report_realized_provision(
        ref,
        request_id,
        resources,
        {
            "raes_status": "succeeded",
            "members": members,
            **observations,
            "completion": completion,
            **vpn_access_fragment(apply_result.get("vpn_access")),
        },
    )


def _apply_guest_callbacks(options: RaesGceApplyOptions, plugins: GuestPluginPlans | None) -> RaesGceApplyOptions:
    """Bind only the admitted adapter callback to the existing guest driver."""
    return replace(options, runtime_plugin=plugins.execute if plugins is not None else None)


def _provision_evidence(
    run: RaesOperationRun,
    cloud: RegisteredProjectRuntime | None,
    observed: dict[str, GcpProjectState],
    config: GCERangeCellConfig | None,
    result: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, object]], dict[str, Any]]:
    """Retain original plan identities and require provider-backed completion for cloud nodes."""
    resources = snapshot_resources(
        parse_plan(run.input.plan, cloud_admitted=cloud is not None),
        verified_composition_addresses(result.get("composition_verified_addresses")),
    )
    members = _realized_members(result)
    completion = build_completion_evidence(
        run.input.plan,
        resources=resources,
        operating_systems=result.get("operating_systems"),
        compute_substrates=result.get("compute_substrates"),
        generation_id=run.operation_id,
        cloud_projects=cloud_completion(cloud, observed, config, result.get("instances")),
    )
    return resources, members, completion


def _report_realized_provision(
    ref: OperationRef, request_id: str, resources: list[dict[str, str]], ready: dict[str, Any]
) -> None:
    """Append the realized snapshot and terminal ready result for a provision generation."""
    operation = "provision"
    try:
        _report(ref, operation, ResultStep.RAES_PROVISION_SNAPSHOT, {"resources": resources})
        _report(ref, operation, ResultStep.RAES_TERMINAL_READY, ready)
    except Exception as exc:
        # A rejected result must terminate its generation. Retain allocations for
        # normal destroy, which also removes OpenVPN and registered cloud state.
        reason_code, diagnostic = _classify_failure(exc, "raes range provision result")
        logger.error(
            "RAES range provision result was rejected for request_id=%s exc_type=%s",
            request_id,
            type(exc).__name__,
            exc_info=False,
        )
        _report_failure(ref, operation, diagnostic, reason_code)
        raise


def _release_failed_provision_allocation(
    run: RaesOperationRun,
    raes_plan: RaesPlan | None,
    config: GCERangeCellConfig | None,
    network_allocation: GceNetworkAllocation | None,
    pre_mutation_release_attempted: bool,
) -> None:
    """Release failed GCE addressing only after proving original resources absent."""
    if (
        network_allocation is not None
        and network_allocation.network_cidrs
        and raes_plan is not None
        and config is not None
        and not pre_mutation_release_attempted
    ):
        cleanup_inventory = _raes_cleanup_inventory(
            run.request_id,
            run.input.legacy_range_id,
            raes_plan,
            _destroy_options(config, network_allocation, run.input),
        )
        if cleanup_inventory.get("outcome") == VERIFIED_ABSENT:
            _release_subnet_allocations_best_effort(run.request_id, operation_id=run.operation_id)


def run_raes_range_activate(request_id: str, *, operation_id: str | None = None) -> None:
    """Activate a warm claim only after old access is revoked and claimant access is verified.

    A failed generation terminates and retains its normal destroy authority.
    """
    from uuid import UUID

    from raes_gcp_activate import activate_raes_range_cell, default_activation_ops

    operation = "activate"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    try:
        run = get_activation_operation_input(generation, request_id=request_id)
    except Exception:
        _report_failure(
            provisional_ref, operation, "operation input could not be read or validated", _INPUT_REASON_CODE
        )
        raise
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    activation = run.input

    logger.info("Starting RAES range activation for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_ACTIVATE_RUNNING, {"raes_status": "running"})
    try:
        operation_input = activation.raes_input
        if operation_input.runtime_plugin is not None or operation_input.gcp_projects or operation_input.cloud_content:
            raise RaesRealizationError("Runtime plugin and cloud warm activation are not supported")
        backend = _require_gce_live_fire_binding(operation_input)
        config = _config_for_range_placement(request_id, load_gce_range_cell_config(backend=backend))
        raes_plan = parse_plan(operation_input.plan)
        network_allocation = _allocated_networks_for_destroy(
            request_id,
            run.operation_id,
            raes_plan,
            config,
        )
        # The claimant's OpenVPN credentials, keyed on the range's request id like
        # a cold provision; the warm-prepare generation never held any (#2030).
        openvpn = prepare_raes_openvpn(
            run.request_id, activation.legacy_range_id, raes_plan, operation_input.remote_access
        )
        result = activate_raes_range_cell(
            activation=activation,
            prepared_generation=UUID(activation.prepared_generation_fence),
            activate_generation=UUID(run.operation_id),
            ops=default_activation_ops(
                config=config,
                allocated_network_cidrs=network_allocation.require_available(),
                openvpn=openvpn,
            ),
        )
        resources = result.completion["resources"]
    except Exception as exc:
        reason_code, diagnostic = _classify_failure(exc, "raes range activate")
        logger.error(
            "RAES range activation failed for request_id=%s exc_type=%s", request_id, type(exc).__name__, exc_info=False
        )
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    _report(ref, operation, ResultStep.RAES_ACTIVATE_SNAPSHOT, {"resources": resources})
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_READY,
        {
            "raes_status": "succeeded",
            "members": result.members,
            "completion": result.completion,
            **vpn_access_fragment(result.vpn_access),
        },
    )


def _destroy_options(
    config: GCERangeCellConfig, network_allocation: GceNetworkAllocation, operation_input: RaesOperationInput
) -> RaesGceDestroyOptions:
    """Return the reconstructive destroy options shared by teardown and its inventory."""
    return RaesGceDestroyOptions(
        config=config,
        allocated_network_cidrs=network_allocation.network_cidrs or None,
        reconstruct_without_allocation=network_allocation.required and not network_allocation.network_cidrs,
        remote_access=vpn_access_names(operation_input.remote_access),
    )


def _raes_cleanup_inventory(
    request_id: str, range_id: int, raes_plan: RaesPlan, options: RaesGceDestroyOptions
) -> dict[str, Any]:
    """Inventory owned resources after a successful destroy; never fail the terminal report.

    A failed inventory yields ``INCOMPLETE`` (unknown, never an empty success), so
    the destroy still terminalizes but no consumer treats it as verified cleanup.
    """
    try:
        return inventory_raes_range_cell(request_id, range_id, raes_plan, options)
    except Exception:
        logger.exception("RAES cleanup inventory failed for request_id=%s", request_id)
        return {"outcome": "INCOMPLETE", "residual_categories": [], "scope": {}}


def run_raes_range_destroy(request_id: str, *, operation_id: str | None = None) -> None:
    """Tear down every GCE resource owned by an RAES range cell for a generation."""
    operation = "destroy"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    run = _load_input(provisional_ref, generation, operation, request_id)
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    operation_input = run.input
    range_id = operation_input.legacy_range_id

    logger.info("Starting RAES range destroy for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_DESTROY_RUNNING, {"raes_status": "running"})
    try:
        effective_run, no_effects = cleanup_preparation(run)
        operation_input = effective_run.input
        if no_effects is not None:
            _report(
                ref,
                operation,
                ResultStep.RAES_TERMINAL_DESTROYED,
                {"raes_status": "succeeded", "cleanup_inventory": no_effects},
            )
            return
        raes_plan, cloud = prepare_cloud_plan(run, effective_run, cleanup_only=True)
        if operation_input.range_backend == "ec2":
            from raes_ec2_runtime import destroy_ec2_run

            cleanup_inventory = destroy_ec2_run(effective_run)
            _report(
                ref,
                operation,
                ResultStep.RAES_TERMINAL_DESTROYED,
                {"raes_status": "succeeded", "cleanup_inventory": cleanup_inventory},
            )
            return
        backend = _require_gce_live_fire_binding(operation_input)
        config = load_gce_range_cell_config(backend=backend)
        config = _config_for_range_placement(request_id, config)
        network_allocation = _allocated_networks_for_destroy(
            request_id,
            generation,
            raes_plan,
            config,
        )
        destroy_options = _destroy_options(config, network_allocation, operation_input)
        destroy_raes_range_cell(request_id, range_id, raes_plan, destroy_options)
        # The gateway is gone; delete the generation's OpenVPN credentials (#2030).
        cleanup_raes_openvpn(run.request_id, range_id, operation_input.remote_access)
    except Exception as exc:
        reason_code, diagnostic = _classify_failure(exc, "raes range destroy")
        logger.error(
            "RAES range destroy failed for request_id=%s exc_type=%s", request_id, type(exc).__name__, exc_info=False
        )
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    # Independent inventory/readback of owned resources -- verified cleanup requires
    # this evidence, not the delete loop completing (#2086, ADR-063-R4/R5). The
    # reservation remains held until absence is proven so another range cannot
    # reuse an occupied CIDR after a partial or unreadable cleanup.
    cleanup_inventory = _raes_cleanup_inventory(request_id, range_id, raes_plan, destroy_options)
    cleanup_inventory = restore_cloud_projects(cloud, cleanup_inventory)
    if network_allocation.network_cidrs and cleanup_inventory.get("outcome") == VERIFIED_ABSENT:
        _release_subnet_allocations_best_effort(request_id, operation_id=generation)
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {"raes_status": "succeeded", "cleanup_inventory": cleanup_inventory},
    )
