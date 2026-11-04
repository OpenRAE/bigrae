"""Verify the installed owner process against its actual Kubernetes container."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from shared.model_access.network import private_listener_address
from shared.participant_control_installation import NativeControlInstallation

OWNER_NAME = "participant-control-0"
OWNER_SERVICE_ACCOUNT = "participant-control"
OWNER_ARGS = ["python", "-m", "cms.participant_control_worker"]

if TYPE_CHECKING:
    from kubernetes.client import V1Pod


def verify_owner_pod(installation: NativeControlInstallation, pod: V1Pod, *, uid: str, address: str) -> str:
    """Reject a desired-only image pin, a foreign Pod or a replaced process."""
    unavailable = "Participant control owner identity unavailable"
    if not uid or not address:
        raise ValueError(unavailable)
    containers = list(pod.spec.containers or [])
    statuses = list(pod.status.container_statuses or [])
    if (
        pod.metadata.name != OWNER_NAME
        or pod.metadata.namespace != installation.namespace
        or pod.metadata.uid != uid
        or pod.metadata.deletion_timestamp is not None
        or pod.status.phase != "Running"
        or pod.status.pod_ip != address
        or pod.spec.service_account_name != OWNER_SERVICE_ACCOUNT
        or len(containers) != 1
        or len(statuses) != 1
    ):
        raise ValueError(unavailable)
    container, status = containers[0], statuses[0]
    digest = installation.owner_image.rsplit("@", 1)[1]
    if (
        container.name != "participant-control"
        or container.image != installation.owner_image
        or container.command
        or list(container.args or []) != OWNER_ARGS
        or status.name != container.name
        or not status.container_id
        or status.state.running is None
        or not isinstance(status.image_id, str)
        or not status.image_id.endswith("@" + digest)
    ):
        raise ValueError(unavailable)
    return private_listener_address(address)


def installed_owner_address(installation: NativeControlInstallation) -> str:
    """Use in-cluster credentials only; never fall back to a developer kubeconfig."""
    from importlib import import_module

    kubernetes = import_module("kubernetes")
    kubernetes.config.load_incluster_config()
    pod = kubernetes.client.CoreV1Api().read_namespaced_pod(
        name=OWNER_NAME,
        namespace=installation.namespace,
        _request_timeout=(1, 2),
    )
    return verify_owner_pod(
        installation,
        pod,
        uid=os.environ.get("PARTICIPANT_CONTROL_POD_UID", ""),
        address=os.environ.get("PARTICIPANT_CONTROL_POD_IP", ""),
    )
