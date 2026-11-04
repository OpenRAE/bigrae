"""Authenticate a live reserved task through Kubernetes' bound-token authority.

This establishes workload identity only. Operation authority, generation and
exclusive invocation permission remain the owning service's responsibilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from pydantic import SecretStr

from shared.cloud.exceptions import CloudTaskError

from ._helpers import _api_call
from ._interrupt import _is_reserved_intent
from ._job_lifecycle import _matches_required_model

_UNAVAILABLE = "Workload authentication unavailable"
_TIMEOUT = (1, 2)


@dataclass(frozen=True, slots=True)
class VerifiedTaskWorkload:
    """Server-observed identity; no token or caller-provided authorization."""

    namespace: str
    pod_name: str
    pod_uid: str
    job_uid: str
    service_account: str
    container_id: str


def _single(extra: object, name: str) -> str:
    if not isinstance(extra, dict):
        raise ValueError(_UNAVAILABLE)
    values = extra.get("authentication.kubernetes.io/" + name)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or not values[0]:
        raise ValueError(_UNAVAILABLE)
    return values[0]


@dataclass(frozen=True, slots=True)
class KubernetesWorkloadClients:
    """Installation-owned Kubernetes clients; token claims never choose these endpoints."""

    authentication: object
    core: object
    batch: object


@dataclass(frozen=True, slots=True)
class _TokenSubject:
    namespace: str
    pod_name: str
    pod_uid: str
    service_account: str


def verify_task_workload_token(
    clients: KubernetesWorkloadClients,
    *,
    token: SecretStr,
    audience: str,
    namespace: str,
    task_ref: str,
    expected_identity: dict[str, Any],
) -> VerifiedTaskWorkload:
    """Review the token, then independently join the live Pod and reserved Job.

    Clients are installation-owned. No token claims select a client, cluster or
    namespace. Fixed API timeouts bound each connect/read; no call is retried.
    Every failure is value-free, including a foreign API exception.
    """
    try:
        return _verify(clients, token, audience, namespace, task_ref, expected_identity)
    except Exception:  # noqa: BLE001  # authentication boundary; provider failures cannot expose token material
        raise CloudTaskError(_UNAVAILABLE) from None


def _verify(
    clients: KubernetesWorkloadClients,
    token: SecretStr,
    audience: str,
    namespace: str,
    task_ref: str,
    expected: dict[str, Any],
) -> VerifiedTaskWorkload:
    if not isinstance(token, SecretStr) or not audience or not namespace or not task_ref.startswith(namespace + "/"):
        raise ValueError(_UNAVAILABLE)
    encoded = token.get_secret_value()
    if not 1 <= len(encoded) <= 16384 or not encoded.isascii() or any(c.isspace() for c in encoded):
        raise ValueError(_UNAVAILABLE)
    job_name = task_ref.removeprefix(namespace + "/")
    if not job_name or "/" in job_name:
        raise ValueError(_UNAVAILABLE)
    response = _api_call(
        clients.authentication,
        "create_token_review",
        body={
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "spec": {"token": encoded, "audiences": [audience]},
        },
        _request_timeout=_TIMEOUT,
    )
    status = cast(Any, response).status
    account = expected["service_account_name"] or "default"
    if status.authenticated is not True or status.error or status.audiences != [audience]:
        raise ValueError(_UNAVAILABLE)
    if status.user.username != f"system:serviceaccount:{namespace}:{account}" or not status.user.uid:
        raise ValueError(_UNAVAILABLE)
    pod_name, pod_uid = _single(status.user.extra, "pod-name"), _single(status.user.extra, "pod-uid")
    pod = _api_call(clients.core, "read_namespaced_pod", name=pod_name, namespace=namespace, _request_timeout=_TIMEOUT)
    job = _api_call(clients.batch, "read_namespaced_job", name=job_name, namespace=namespace, _request_timeout=_TIMEOUT)
    return _verify_live_job(_TokenSubject(namespace, pod_name, pod_uid, account), pod, job, job_name, expected)


def _verify_live_job(
    subject: _TokenSubject,
    pod: object,
    job: object,
    job_name: str,
    expected: dict[str, Any],
) -> VerifiedTaskWorkload:
    """Join the authenticated subject with the live controller, container, and reserved Job."""
    namespace, pod_name, pod_uid, account = (
        subject.namespace,
        subject.pod_name,
        subject.pod_uid,
        subject.service_account,
    )
    meta = cast(Any, pod).metadata
    pod_spec = cast(Any, pod).spec
    pod_status = cast(Any, pod).status
    if (meta.name, meta.namespace, meta.uid) != (pod_name, namespace, pod_uid) or meta.deletion_timestamp is not None:
        raise ValueError(_UNAVAILABLE)
    if pod_status.phase != "Running" or pod_spec.service_account_name != account:
        raise ValueError(_UNAVAILABLE)
    job_meta = cast(Any, job).metadata
    job_spec = cast(Any, job).spec
    job_status = cast(Any, job).status
    if (
        (job_meta.name, job_meta.namespace) != (job_name, namespace)
        or not job_meta.uid
        or job_meta.deletion_timestamp is not None
    ):
        raise ValueError(_UNAVAILABLE)
    if job_status.succeeded or job_status.failed or not _is_reserved_intent(job, job_name, expected):
        raise ValueError(_UNAVAILABLE)
    controllers = [owner for owner in meta.owner_references or [] if owner.controller is True]
    if len(controllers) != 1:
        raise ValueError(_UNAVAILABLE)
    owner = controllers[0]
    if (owner.api_version, owner.kind, owner.name, owner.uid) != ("batch/v1", "Job", job_name, job_meta.uid):
        raise ValueError(_UNAVAILABLE)
    if not _matches_required_model(pod_spec, job_spec.template.spec):
        raise ValueError(_UNAVAILABLE)
    statuses = list(pod_status.container_statuses or [])
    if len(statuses) != 1 or statuses[0].name != expected["container_name"]:
        raise ValueError(_UNAVAILABLE)
    running = statuses[0]
    digest = expected["image"].rsplit("@", 1)[-1]
    image_id = running.image_id
    if (
        re.fullmatch(r"sha256:[a-f0-9]{64}", digest) is None
        or not isinstance(image_id, str)
        or image_id.rsplit("@", 1)[-1] != digest
        or running.state.running is None
        or not isinstance(running.container_id, str)
        or not 1 <= len(running.container_id) <= 256
        or getattr(pod_spec, "ephemeral_containers", None)
    ):
        raise ValueError(_UNAVAILABLE)
    return VerifiedTaskWorkload(namespace, pod_name, pod_uid, job_meta.uid, account, running.container_id)
