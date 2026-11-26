"""Domain entry points that enqueue provisioner launches.

Each ``start_*`` function builds a canonical provisioner command and persists a
launch intent. The launcher worker dispatches the intent through ``engine.ecs``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID
from uuid import UUID as UUIDType

from engine.ecs._config import _get_engine_task_config
from engine.ecs._local import _is_local_provisioner_enabled, _run_local_provisioner
from engine.ecs._validation import _validate_start_ecs_task_args
from engine.services._launch_intents import enqueue_provisioner_launch, task_ref_for_intent
from shared.enums import ResourceType

if TYPE_CHECKING:
    from shared.credentials import CredentialContext

# Keep the pre-split ``engine.ecs`` logger name so log routing and dashboards do not change.
logger = logging.getLogger("engine.ecs")

# SonarCloud S1192: extracted duplicated string literals.
REQUEST_ID_NONE_MSG = "request_id cannot be None"


def _enqueue_provisioner_launch(command: list[str], *, credential: CredentialContext | None = None) -> str | None:
    """Persist one durable ``ProvisionerLaunchIntent`` for the launcher worker and
    return its reserved task ref.

    Provider-neutral (ADR-043-R2): AWS and GCP share this single launch-intent
    contract. There is no synchronous provider dispatch here; the active
    ``TaskRunner.run_task`` is reached only by the ``drain_provisioner_launch_outbox``
    worker through :func:`dispatch_provisioner_command`. Returns ``None`` when the
    engine task runner is not configured, so a misconfigured provider does not
    persist an intent the launcher can never execute (a ghost launch). The domain
    operation generation is reserved and fenced inside
    ``engine.services._launch_intents.enqueue_provisioner_launch`` for both providers.
    """
    if _get_engine_task_config() is None:
        return None

    intent_id = enqueue_provisioner_launch(command, credential=credential)
    return task_ref_for_intent(intent_id)


def _start_ecs_task(range_id: int, user_id: int, command: str) -> str | None:
    """Start an ECS Fargate task for provisioning operations.

    Args:
        range_id: Database ID of the Range
        user_id: Django User ID of the User
        command: Command to run ("provision" or "destroy")

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured. The launcher worker submits the provider task later.

    Raises:
        TypeError: If range_id is not an integer or user_id is not an integer or command is not a string
        ValueError: If range_id is negative or user_id is negative or command is empty,
            or if current domain state does not authorize the operation
    """
    _validate_start_ecs_task_args(range_id, user_id, command)

    command_list = [
        ResourceType.RANGE.value,
        command,
        "--range-id",
        str(range_id),
        "--user-id",
        str(user_id),
    ]
    logger.info("Enqueuing provisioner launch intent range_id=%s command=%s", range_id, command)
    return _enqueue_provisioner_launch(command_list)


def start_provisioning(range_id: int, user_id: int) -> str | None:
    """Start provisioning a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to provision
        user_id: Django User ID of the User
    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        ValueError: If current domain state does not authorize the operation
    """
    return _start_ecs_task(range_id, user_id, "provision")


def start_teardown(range_id: int, user_id: int) -> str | None:
    """Start teardown of a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to teardown
        user_id: User ID for event publishing in the provisioner

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        ValueError: If current domain state does not authorize the operation

    .. deprecated::
        Use :func:`start_range_teardown` instead.
    """
    return _start_ecs_task(range_id, user_id, "destroy")


def _dispatch_remote_provisioner_task(
    command: list[str],
    request_id: UUID,
    resource: str,
    *,
    credential: CredentialContext | None = None,
) -> str | None:
    """Enqueue a durable launch intent for a request-based remote operation.

    The ``drain_provisioner_launch_outbox`` worker later submits the provider
    task; nothing here calls ``TaskRunner.run_task`` directly (ADR-043-R2).
    """
    logger.info("Enqueuing %s launch intent for request_id=%s", resource, request_id)
    return _enqueue_provisioner_launch(command, credential=credential)


def _start_range_ecs_task(
    request_id: UUID,
    command: str,
    resource: str = "range",
    *,
    credential: CredentialContext | None = None,
) -> str | None:
    """Start an ECS Fargate task for Range operations using request_id.

    Matches NGFW pattern - provisioner fetches all data from DB using request_id.

    Args:
        request_id: UUID of the Request to operate on
        command: Command to run ("provision" or "destroy")
        resource: Provisioner subcommand/resource group. RAES lifecycle calls
            pass ``"raes-range"`` so the provisioner realizes a persisted
            serialized RAES plan (ADR-031/ADR-032); the local/ECS dispatch
            mechanics are otherwise identical.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If command is invalid
        ValueError: If current domain state does not authorize the operation
    """

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    valid_commands = ("provision", "destroy", "pause", "resume")
    if command not in valid_commands:
        raise ValueError(f"Invalid command: {command}. Must be one of {valid_commands}.")

    command_list = [resource, command, "--request-id", str(request_id)]
    if _is_local_provisioner_enabled():
        logger.info(
            "Using local provisioner for %s request_id=%s command=%s",
            resource,
            request_id,
            command,
        )

        intent_id = enqueue_provisioner_launch(command_list, credential=credential)
        return task_ref_for_intent(intent_id) or f"local-pending:{intent_id}"
    return _dispatch_remote_provisioner_task(command_list, request_id, resource, credential=credential)


def start_range_provisioning(request_id: UUID, *, credential: CredentialContext | None = None) -> str | None:
    """Start provisioning a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    return _start_range_ecs_task(request_id, "provision", credential=credential)


def start_raes_range_provisioning(request_id: UUID, *, credential: CredentialContext | None = None) -> str | None:
    """Provision an RAES-native range through its request-bound lifecycle command.

    Identical dispatch mechanics to :func:`start_range_provisioning` (local
    subprocess or ECS Fargate); only the provisioner subcommand differs, so the
    provisioner realizes a persisted serialized RAES plan rather than a RangeSpec.

    Returns:
        Task ARN / local handle if dispatched, None if ECS is not configured.
    """
    return _start_range_ecs_task(request_id, "provision", resource="raes-range", credential=credential)


def start_raes_range_teardown(request_id: UUID, *, credential: CredentialContext | None = None) -> str | None:
    """Destroy an RAES-native range through its request-bound lifecycle command.

    Identical dispatch mechanics to :func:`start_range_teardown`; only the
    provisioner subcommand differs, so the provisioner reconstructs the range
    resources from the persisted serialized RAES plan and deletes them.

    Returns:
        Task ARN / local handle if dispatched, None if ECS is not configured.
    """
    return _start_range_ecs_task(request_id, "destroy", resource="raes-range", credential=credential)


def start_range_teardown(request_id: UUID, *, credential: CredentialContext | None = None) -> str | None:
    """Start teardown of a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to teardown.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    return _start_range_ecs_task(request_id, "destroy", credential=credential)


def start_range_operation(
    request_id: UUID, operation: str, *, credential: CredentialContext | None = None
) -> str | None:
    """Start a range runtime operation (pause/resume) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the Range.
        operation: Operation to perform ('pause' or 'resume').

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'pause' or 'resume'
        ValueError: If current domain state does not authorize the operation
    """

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("pause", "resume"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'pause' or 'resume'.")

    return _start_range_ecs_task(request_id, operation, credential=credential)


def _start_ngfw_ecs_task(request_id: UUID, command: list[str]) -> str | None:
    """Start an ECS Fargate task for NGFW operations.

    Args:
        request_id: UUID of the Request to operate on
        command: Command list to run (e.g., ["ngfw", "provision", "--request-id", "..."])

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured

    Raises:
        TypeError: If request_id is None or command is not a list
        ValueError: If command is empty
        ValueError: If current domain state does not authorize the operation
    """

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if command is None or not isinstance(command, list):
        raise TypeError("command must be a list")
    if not command:
        raise ValueError("command must be a non-empty list")

    if _is_local_provisioner_enabled():
        logger.info(
            "Using local provisioner for NGFW request_id=%s command=%s",
            request_id,
            command,
        )
        return _run_local_provisioner(command)
    return _dispatch_remote_provisioner_task(command, request_id, "NGFW")


def start_ngfw_provisioning(request_id: UUID) -> str | None:
    """Start provisioning an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    command = ["ngfw", "provision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_teardown(request_id: UUID) -> str | None:
    """Start teardown/deprovision of an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to deprovision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    command = ["ngfw", "deprovision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_operation(request_id: UUID, operation: str) -> str | None:
    """Start an NGFW runtime operation (start/stop) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the NGFW instance.
        operation: Operation to perform ('start' or 'stop').

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'start' or 'stop'
        ValueError: If current domain state does not authorize the operation
    """

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("start", "stop"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'start' or 'stop'.")

    command = ["ngfw", operation, "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)
