"""ECS Fargate / GCP task orchestration for Shifter Engine (package facade).

This package triggers provisioner tasks to provision and teardown range
infrastructure. The Shifter Engine writes directly to the database, so no
callback endpoint is needed.

Local Development:
    Set LOCAL_PROVISIONER=subprocess in settings to run the provisioner locally
    instead of triggering a remote task. This requires:
    - AWS credentials configured
    - PROVISIONER_PATH setting pointing to the provisioner directory

The implementation is split by responsibility across private submodules
(``_env`` GCP Job env projection, ``_config`` task-runner config, ``_local``
local subprocess fallback, ``_status`` task-status projection) and re-exported
here (#685) so callers keep using ``from engine.ecs import X``. Provider
dispatch stays in this facade. The ``start_*`` launch entry points live in
``engine.services._launch_starts`` because they enqueue launch intents.
"""

from __future__ import annotations

from django.conf import settings

from engine.launch_commands import validate_provisioner_command
from shared.cloud import PROVISIONER_CONTAINER_NAME, get_task_runner

from ._config import _get_engine_task_config
from ._env import (
    _AWS_PROVISIONER_ENV_KEYS,
    _GCP_PROVISIONER_ENV_KEYS,
    _get_aws_provisioner_env_overrides,
    _get_gcp_provisioner_env_overrides,
    _get_provisioner_env_overrides,
)
from ._local import _is_local_provisioner_enabled, _run_local_provisioner
from ._status import get_task_status
from ._workload import assert_provisioner_workload


def dispatch_provisioner_command(
    command: list[str], *, task_identity: str | None = None, expected_workload: dict[str, object] | None = None
) -> str | None:
    """Launch one validated command directly; callable only by the launcher worker on GCP."""

    validate_provisioner_command(command)
    if expected_workload is not None:
        assert_provisioner_workload(expected_workload, command, task_identity)
    if _is_local_provisioner_enabled():
        return _run_local_provisioner(command)
    task_config = _get_engine_task_config()
    if task_config is None:
        return None
    cluster, task_definition, network_config = task_config
    runner = get_task_runner()
    return runner.run_task(
        task_definition=task_definition,
        cluster=cluster,
        command=command,
        container_name=PROVISIONER_CONTAINER_NAME,
        env_overrides=_get_provisioner_env_overrides(),
        network_config=network_config,
        task_identity=task_identity,
    )


def interrupt_provisioner_task(
    task_ref: str, command: list[str], task_identity: str, *, expected_workload: dict[str, object] | None = None
) -> str | None:
    """Interrupt a dispatched provisioner task; callable only by the launcher worker (#277).

    Resolves the provider task runner and verifies the workload against the trusted
    launch identity (image/command/container/service-account + the deterministic
    Job identity) before stopping it. Returns a ``TaskInterruptDisposition`` value,
    or ``None`` when the engine task runner is not configured.
    """

    if expected_workload is not None:
        namespace = expected_workload.get("namespace")
        job_name = expected_workload.get("job_name")
        if not isinstance(namespace, str) or not isinstance(job_name, str):
            raise ValueError("Provisioner interrupt identity unavailable")
        if (
            expected_workload.get("provider") != settings.CLOUD_PROVIDER
            or expected_workload.get("command") != command
            or expected_workload.get("task_identity") != task_identity
            or task_ref != namespace + "/" + job_name
        ):
            raise ValueError("Provisioner interrupt identity changed")
        expected_identity = {
            key: expected_workload[key]
            for key in ("task_identity", "image", "command", "container_name", "service_account_name")
        }
        return get_task_runner().interrupt_task(namespace, task_ref, expected_identity)
    task_config = _get_engine_task_config()
    if task_config is None:
        return None
    cluster, task_definition, _network_config = task_config
    runner = get_task_runner()
    expected_identity = {
        "task_identity": task_identity,
        "image": task_definition,
        "command": command,
        "container_name": PROVISIONER_CONTAINER_NAME,
        "service_account_name": str(getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "") or ""),
    }
    return runner.interrupt_task(cluster, task_ref, expected_identity)


# =============================================================================
# Request-based Range ECS Functions (new pattern matching NGFW)
# =============================================================================


__all__ = [
    # Internal seams re-exported for tests, kept stable across the #685 split.
    "_AWS_PROVISIONER_ENV_KEYS",
    "_GCP_PROVISIONER_ENV_KEYS",
    "_get_aws_provisioner_env_overrides",
    "_get_engine_task_config",
    "_get_gcp_provisioner_env_overrides",
    "_get_provisioner_env_overrides",
    "_is_local_provisioner_enabled",
    "_run_local_provisioner",
    # Public provisioner dispatch entrypoints.
    "dispatch_provisioner_command",
    "get_task_status",
]
