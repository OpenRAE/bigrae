"""GCE range-cell guest power operations (pause/resume) for issue #614.

Stops and starts a Compute Engine range-cell VM through the existing
``ComputeInstancesClient`` and observes the resulting instance state, so a range
pause/resume reaches its declared postcondition (ADR-039) rather than trusting
that the provider accepted the request. Only an observed persistent-disk
footprint without an independent instance controller is admitted. Stop/start
does not preserve RAM or application execution.

Addressing comes from the per-instance state persisted by the range-cell output
builder. Those provider-prefixed output keys are persisted into
``engine_instance.state`` under ``provider_metadata.gcp`` with the ``gcp_``
prefix removed (``project_id``, ``zone``, ``instance_name``) by
``state_helpers._build_instance_state``; the raw provisioner output carries the
same values under the ``gcp_``-prefixed top-level keys. Both shapes are accepted.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, cast
from uuid import UUID

from shared.native_power import GcePowerIncarnation, GcePowerTarget, parse_gce_power_target

from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_ops import _wait_for_operation
from gcp_range_cell_types import RangeCellPlan
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

# Compute Engine terminal instance states for the two power operations.
_STOPPED_STATUS = "TERMINATED"
_RUNNING_STATUS = "RUNNING"

_EXPECTED_STATUS = {"stop": _STOPPED_STATUS, "start": _RUNNING_STATUS}


def _gcp_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the ``provider_metadata.gcp`` block of a persisted instance state."""
    provider_metadata = state.get("provider_metadata")
    if isinstance(provider_metadata, dict):
        metadata = provider_metadata.get("gcp")
        if isinstance(metadata, dict):
            return metadata
    return {}


def _resolve_power_target(state: dict[str, Any]) -> tuple[str, str, str]:
    """Resolve the (project, zone, instance) a GCE power op addresses from state.

    Reads the persisted ``provider_metadata.gcp`` block first (``project_id`` /
    ``zone`` / ``instance_name``), falling back to the raw provisioner output's
    ``gcp_``-prefixed top-level keys and ``instance_id``.
    """
    metadata = _gcp_metadata(state)
    project = str(metadata.get("project_id") or state.get("gcp_project_id") or "").strip()
    zone = str(metadata.get("zone") or state.get("gcp_zone") or "").strip()
    instance = str(
        metadata.get("instance_name") or state.get("gcp_instance_name") or state.get("instance_id") or ""
    ).strip()
    if not all([project, zone, instance]):
        raise RuntimeError(
            "GCE range-cell power operation requires project, zone, and instance name in state "
            "(provider_metadata.gcp or gcp_-prefixed output keys)"
        )
    return project, zone, instance


def _instance_status(instance: object) -> str:
    """Read a Compute instance status from an SDK object or dict response."""
    if isinstance(instance, dict):
        return str(instance.get("status", "")).upper()
    return str(getattr(instance, "status", "") or "").upper()


def _field(value: object, name: str, wire_name: str | None = None) -> object:
    """Read a provider response from the discovery client or a typed client."""
    if isinstance(value, dict):
        return value.get(wire_name or name)
    return getattr(value, name, None)


def _persistent_footprint(instance: object) -> tuple[str, tuple[str, ...]]:
    """Reject unobserved or independently controlled resources before power calls."""
    identifier = _instance_identity(instance)
    disks = _observed_sequence(_field(instance, "disks"))
    policies = _observed_sequence(_field(instance, "resource_policies", "resourcePolicies"))
    metadata = _field(instance, "metadata")
    raw_items = _field(metadata, "items")
    if metadata is not None and raw_items is None and not isinstance(metadata, dict):
        raise RuntimeError("GCE power footprint metadata is invalid")
    items = _observed_sequence(raw_items)
    if not disks or policies:
        raise RuntimeError("GCE power footprint is unsupported")
    if any(_field(item, "key") == "created-by" for item in (items or ())):
        raise RuntimeError("GCE power footprint has an independent instance controller")
    sources = []
    for disk in disks:
        kind = _field(disk, "type_", "type")
        source = _field(disk, "source")
        if kind != "PERSISTENT" or not isinstance(source, str) or not source:
            raise RuntimeError("GCE power footprint requires observed persistent disks")
        sources.append(source)
    if len(sources) != len(set(sources)):
        raise RuntimeError("GCE power footprint repeats a disk")
    return identifier, tuple(sorted(sources))


def _instance_identity(instance: object) -> str:
    """Keep the observed provider incarnation separate from its reusable name."""
    value = _field(instance, "id")
    if type(value) not in (int, str):
        raise RuntimeError("GCE power footprint instance identity is invalid")
    identifier = str(value)
    if not identifier.isascii() or not identifier.isdecimal() or not 0 < int(identifier) < 2**64:
        raise RuntimeError("GCE power footprint instance identity is invalid")
    return identifier


def _observed_sequence(value: object) -> Sequence[object]:
    """An absent optional provider array is empty; malformed arrays are refused."""
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) > 256:
        raise RuntimeError("GCE power footprint observation is invalid")
    return value


def observe_power_footprints(
    states: Sequence[dict[str, Any]], *, clients: GCEClients | None = None
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Inspect the whole range without mutation, using one read-only client."""
    if not states:
        return ()
    resolved = clients or _build_clients()
    footprints = []
    for state in states:
        project, zone, instance = _resolve_power_target(state)
        footprints.append(_persistent_footprint(resolved.instances.get(project=project, zone=zone, instance=instance)))
    return tuple(footprints)


def _native_invocation_options(
    state: dict[str, Any],
    project: str,
    zone: str,
    instance: str,
    expected_incarnation: GcePowerIncarnation | None,
    before_invoke: Callable[[], None] | None,
    invocation_id: UUID | None,
) -> tuple[GcePowerTarget | None, dict[str, object], dict[str, object]]:
    """Bind native identity and bounded no-retry transport before reading or invoking."""
    native_target = None
    native_options: dict[str, object] = {}
    read_options: dict[str, object] = {}
    if expected_incarnation is not None:
        if before_invoke is None:
            raise RuntimeError("Native power invocation requires current authority")
        if not isinstance(invocation_id, UUID) or invocation_id.int == 0:
            raise RuntimeError("Native power invocation identity is unavailable")
        # A retry inside the cloud SDK would bypass the native per-call fence.
        native_options = {"request_id": str(invocation_id), "retry": None, "timeout": 10.0}
        read_options = {"retry": None, "timeout": 10.0}
        native_target = parse_gce_power_target(state.get("native_power_target"), instance_id=instance)
        if (native_target.project_id, native_target.zone, native_target.instance_name) != (project, zone, instance):
            raise RuntimeError("Native power target does not match invocation")
    return native_target, native_options, read_options


def _mutate_power(
    operation: str,
    project: str,
    zone: str,
    instance: str,
    resolved: GCEClients,
    native_options: dict[str, object],
    plan: RangeCellPlan,
) -> None:
    """Issue the selected sole mutation and wait using the existing zonal operation helper."""
    if operation == "stop":
        compute_operation = resolved.instances.stop(project=project, zone=zone, instance=instance, **native_options)
    else:
        compute_operation = resolved.instances.start(project=project, zone=zone, instance=instance, **native_options)
    _wait_for_operation(plan, resolved, compute_operation, "zone")


def run_power_operation(
    operation: str,
    state: dict[str, Any],
    *,
    clients: GCEClients | None = None,
    expected_footprint: tuple[str, tuple[str, ...]] | None = None,
    expected_incarnation: GcePowerIncarnation | None = None,
    before_invoke: Callable[[], None] | None = None,
    invocation_id: UUID | None = None,
) -> None:
    """Run a start/stop power operation against a GCE range-cell VM and observe it.

    Args:
        operation: "start" (resume) or "stop" (pause).
        state: The instance's persisted ``engine_instance.state`` dict.
        clients: Optional injected Compute clients (tests); production builds them.
        expected_footprint: The whole-range preflight's observed incarnation and disks.
        expected_incarnation: Retained VM/disk identities for an admitted native member.
        before_invoke: The installed native owner's current per-call authority fence.
        invocation_id: The durable per-member invocation UUID used for provider deduplication.

    Raises:
        ValueError: On an unknown operation.
        RuntimeError: On incomplete state or when the instance does not reach the
            expected terminal status.
    """
    if operation not in _EXPECTED_STATUS:
        raise ValueError(f"Unknown GCE range-cell operation: {operation}")

    project, zone, instance = _resolve_power_target(state)
    native_target, native_options, read_options = _native_invocation_options(
        state,
        project,
        zone,
        instance,
        expected_incarnation,
        before_invoke,
        invocation_id,
    )
    resolved = clients or _build_clients()
    before_instance = resolved.instances.get(project=project, zone=zone, instance=instance, **read_options)
    before = _persistent_footprint(before_instance)
    if expected_footprint is not None and before != expected_footprint:
        raise RuntimeError("GCE power footprint changed after range admission")
    if native_target is not None:
        from gce_range_cell_incarnation import observe_power_incarnation

        if observe_power_incarnation(native_target, clients=resolved) != expected_incarnation:
            raise RuntimeError("Native power incarnation changed before invocation")
    # ``_wait_for_operation`` only reads project_id/zone for the zone scope; the
    # remaining RangeCellPlan keys are unused here.
    plan = cast(RangeCellPlan, {"project_id": project, "zone": zone, "region": ""})

    if before_invoke is not None:
        before_invoke()

    expected = _EXPECTED_STATUS[operation]
    # Fresh reviewed repair may find a member already at its requested state.
    # It still consumes the exact native authority fence and requires complete
    # readback; it need not issue a redundant mutating request to establish that
    # postcondition. Legacy callers retain their existing dispatch behavior.
    if native_target is None or _instance_status(before_instance) != expected:
        _mutate_power(operation, project, zone, instance, resolved, native_options, plan)

    current = resolved.instances.get(project=project, zone=zone, instance=instance, **read_options)
    if _persistent_footprint(current) != before:
        raise RuntimeError("GCE power readback changed instance identity or persistent disks")
    if native_target is not None and observe_power_incarnation(native_target, clients=resolved) != expected_incarnation:
        raise RuntimeError("Native power incarnation changed after invocation")
    status = _instance_status(current)
    if status != expected:
        raise RuntimeError(
            f"GCE instance name_fp={safe_log_fingerprint(instance)} did not reach {expected} after {operation}"
        )
    logger.info(
        "GCE range-cell %s complete name_fp=%s status=%s",
        operation,
        safe_log_fingerprint(instance),
        expected,
    )
