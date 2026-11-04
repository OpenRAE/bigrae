"""Only the reviewed live Pod for the reserved Job can identify an invoker."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from shared.cloud.exceptions import CloudTaskError


@pytest.fixture
def invocation():
    expected = {
        "task_identity": "fixture-operation",
        "service_account_name": "provisioner",
        "container_name": "provisioner",
        "image": "example.test/provisioner@sha256:" + "a" * 64,
        "command": ["range", "pause"],
    }
    spec = NS(
        service_account_name="provisioner",
        containers=[NS(name="provisioner", image=expected["image"], args=expected["command"])],
    )
    job = NS(
        metadata=NS(
            name="job",
            namespace="tasks",
            uid="job-uid",
            deletion_timestamp=None,
            annotations={"shifter.dev/task-identity": "fixture-operation"},
        ),
        spec=NS(template=NS(spec=spec)),
        status=NS(succeeded=0, failed=0),
    )
    pod = NS(
        metadata=NS(
            name="pod",
            namespace="tasks",
            uid="pod-uid",
            deletion_timestamp=None,
            owner_references=[NS(kind="Job", api_version="batch/v1", name="job", uid="job-uid", controller=True)],
        ),
        spec=deepcopy(spec),
        status=NS(
            phase="Running",
            container_statuses=[
                NS(
                    name=expected["container_name"],
                    image_id=expected["image"],
                    container_id="containerd://synthetic-container",
                    state=NS(running=NS()),
                )
            ],
        ),
    )
    status = NS(
        authenticated=True,
        audiences=["fixture:invocation"],
        error=None,
        user=NS(
            username="system:serviceaccount:tasks:provisioner",
            uid="service-account-uid",
            extra={
                "authentication.kubernetes.io/pod-name": ["pod"],
                "authentication.kubernetes.io/pod-uid": ["pod-uid"],
            },
        ),
    )
    authentication, core, batch = Mock(), Mock(), Mock()
    authentication.create_token_review.return_value = NS(status=status)
    core.read_namespaced_pod.return_value = pod
    batch.read_namespaced_job.return_value = job
    return NS(expected=expected, job=job, pod=pod, status=status, authentication=authentication, core=core, batch=batch)


def verify(item, token=None):
    from shared.cloud.kubernetes.workload_identity import KubernetesWorkloadClients, verify_task_workload_token

    return verify_task_workload_token(
        token=token or SecretStr("synthetic.bound.token"),
        audience="fixture:invocation",
        namespace="tasks",
        task_ref="tasks/job",
        expected_identity=item.expected,
        clients=KubernetesWorkloadClients(authentication=item.authentication, core=item.core, batch=item.batch),
    )


def test_reviewed_live_pod_is_bound_to_the_exact_reserved_job(invocation):
    verified = verify(invocation)
    assert (verified.pod_uid, verified.job_uid, verified.namespace) == ("pod-uid", "job-uid", "tasks")
    request = invocation.authentication.create_token_review.call_args.kwargs
    assert request["body"]["spec"]["audiences"] == ["fixture:invocation"]
    assert request["body"]["spec"]["token"] == "synthetic.bound.token"
    for api in (
        invocation.authentication.create_token_review,
        invocation.core.read_namespaced_pod,
        invocation.batch.read_namespaced_job,
    ):
        assert sum(api.call_args.kwargs["_request_timeout"]) <= 10
    assert "synthetic.bound.token" not in repr(verified)


@pytest.mark.parametrize("fault", ["desired-only-image", "no-container-id", "not-running", "ephemeral"])
def test_workload_requires_the_actual_unmodified_running_container(invocation, fault):
    status = invocation.pod.status.container_statuses[0]
    if fault == "desired-only-image":
        status.image_id = "example.test/old@sha256:" + "b" * 64
    elif fault == "no-container-id":
        status.container_id = ""
    elif fault == "not-running":
        status.state.running = None
    else:
        invocation.pod.spec.ephemeral_containers = [NS(name="debugger")]
    with pytest.raises(CloudTaskError):
        verify(invocation)


@pytest.mark.parametrize(
    "path,value",
    [
        ("status.authenticated", False),
        ("status.audiences", ["other"]),
        ("status.user.username", "system:serviceaccount:other:provisioner"),
        ("status.user.extra", {}),
        ("pod.metadata.uid", "replacement"),
        ("pod.metadata.namespace", "other"),
        ("pod.metadata.deletion_timestamp", "deleted"),
        ("pod.status.phase", "Succeeded"),
        ("job.metadata.deletion_timestamp", "deleted"),
        ("job.status.succeeded", 1),
        ("job.metadata.uid", "replacement"),
        ("job.metadata.name", "other"),
        ("pod.spec.service_account_name", "other"),
    ],
)
def test_mismatched_workload_never_authenticates(invocation, path, value):
    parent = invocation
    *parts, name = path.split(".")
    for part in parts:
        parent = getattr(parent, part)
    setattr(parent, name, value)
    with pytest.raises(CloudTaskError, match="Workload authentication unavailable"):
        verify(invocation)


@pytest.mark.parametrize(
    "change", ["ambiguous-pod", "job-controller", "image", "pod-image", "pod-command", "extra-container"]
)
def test_ambiguous_or_changed_executable_never_authenticates(invocation, change):
    item = invocation
    if change == "ambiguous-pod":
        item.status.user.extra["authentication.kubernetes.io/pod-name"] = ["pod", "other"]
    elif change == "job-controller":
        item.pod.metadata.owner_references[0].controller = False
    elif change == "image":
        item.job.spec.template.spec.containers[0].image = "other"
    elif change == "pod-image":
        item.pod.spec.containers[0].image = "other"
    elif change == "pod-command":
        item.pod.spec.containers[0].args = ["range", "destroy"]
    else:
        item.pod.spec.containers.append(deepcopy(item.pod.spec.containers[0]))
    with pytest.raises(CloudTaskError, match="Workload authentication unavailable"):
        verify(item)


@pytest.mark.parametrize("boundary", ["review", "pod", "job"])
def test_api_failure_is_value_free(invocation, boundary):
    callback = {
        "review": invocation.authentication.create_token_review,
        "pod": invocation.core.read_namespaced_pod,
        "job": invocation.batch.read_namespaced_job,
    }[boundary]
    callback.side_effect = RuntimeError("synthetic-private-provider-diagnostic")
    with pytest.raises(CloudTaskError) as failed:
        verify(invocation)
    assert str(failed.value) == "Workload authentication unavailable"
    assert failed.value.__suppress_context__


def test_explicit_container_identity_tolerates_api_defaults_but_not_changed_images():
    from shared.cloud.kubernetes._job_lifecycle import _matches_required_model

    expected = [NS(image="native", image_pull_policy=None)]
    observed = [NS(image="native", image_pull_policy="IfNotPresent")]
    assert _matches_required_model(observed, expected)
    observed[0].image = "changed"
    assert not _matches_required_model(observed, expected)
    assert not _matches_required_model([*observed, observed[0]], expected)


def test_runner_uses_its_installed_clients_to_authenticate(invocation):
    from shared.cloud.kubernetes import KubernetesTaskRunner
    from tests.shared.cloud.test_kubernetes_task_runner import _profile

    client = NS(AuthenticationV1Api=Mock(return_value=invocation.authentication))
    runner = KubernetesTaskRunner(_profile())
    runner._load_kubernetes_api = Mock(return_value=(invocation.batch, invocation.core, client, RuntimeError))
    verified = runner.authenticate_task_workload(
        cluster="tasks",
        task_ref="tasks/job",
        expected_identity=invocation.expected,
        token=SecretStr("synthetic.bound.token"),
        audience="fixture:invocation",
    )
    assert verified.job_uid == "job-uid"
    client.AuthenticationV1Api.assert_called_once_with(api_client=invocation.batch.api_client)
