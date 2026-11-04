"""The dedicated owner must prove its actual process, storage and lifecycle."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from cms.participant_control_worker import ParticipantControlApplication, installation_owner_lock
from cms.participant_control_worker_identity import OWNER_ARGS, verify_owner_pod
from shared.participant_control_installation import NativeControlInstallation
from tests.shared.test_participant_control_installation import synthetic_installation_values


@pytest.fixture
def installed():
    return NativeControlInstallation.model_validate(synthetic_installation_values())


def _pod(installed):
    return NS(
        metadata=NS(
            name="participant-control-0",
            namespace=installed.namespace,
            uid="synthetic-owner-uid",
            deletion_timestamp=None,
        ),
        spec=NS(
            service_account_name="participant-control",
            containers=[
                NS(
                    name="participant-control",
                    image=installed.owner_image,
                    args=list(OWNER_ARGS),
                    command=None,
                )
            ],
        ),
        status=NS(
            phase="Running",
            pod_ip="10.1.2.3",
            container_statuses=[
                NS(
                    name="participant-control",
                    image_id="docker-pullable://" + installed.owner_image,
                    container_id="containerd://synthetic-running-owner",
                    state=NS(running=NS()),
                )
            ],
        ),
    )


def test_owner_startup_checks_actual_running_container_digest(installed):
    assert verify_owner_pod(installed, _pod(installed), uid="synthetic-owner-uid", address="10.1.2.3") == "10.1.2.3"


@pytest.mark.parametrize(
    "fault",
    [
        "name",
        "namespace",
        "uid",
        "deleting",
        "service-account",
        "two-containers",
        "args",
        "command",
        "desired-image",
        "running-image",
        "not-running",
        "container-id",
        "phase",
        "ip",
        "public-ip",
    ],
)
def test_owner_startup_refuses_unverified_or_replaced_process(installed, fault):
    pod = _pod(installed)
    container, status = pod.spec.containers[0], pod.status.container_statuses[0]
    if fault == "name":
        pod.metadata.name = "participant-control-1"
    elif fault == "namespace":
        pod.metadata.namespace = "foreign"
    elif fault == "uid":
        pod.metadata.uid = "foreign"
    elif fault == "deleting":
        pod.metadata.deletion_timestamp = "now"
    elif fault == "service-account":
        pod.spec.service_account_name = "portal"
    elif fault == "two-containers":
        pod.spec.containers.append(deepcopy(container))
    elif fault == "args":
        container.args = ["python", "manage.py", "shell"]
    elif fault == "command":
        container.command = ["sh", "-c"]
    elif fault == "desired-image":
        container.image = "example.test/unpinned:latest"
    elif fault == "running-image":
        status.image_id = "docker-pullable://example.test/other@sha256:" + "f" * 64
    elif fault == "not-running":
        status.state.running = None
    elif fault == "container-id":
        status.container_id = ""
    elif fault == "phase":
        pod.status.phase = "Pending"
    elif fault == "ip":
        pod.status.pod_ip = "10.1.2.4"
    else:
        pod.status.pod_ip = "8.8.8.8"
    with pytest.raises(ValueError):
        verify_owner_pod(
            installed, pod, uid="synthetic-owner-uid", address="8.8.8.8" if fault == "public-ip" else "10.1.2.3"
        )


def test_installation_lock_excludes_a_second_owner_and_releases_on_exit(tmp_path):
    root = tmp_path / "private-owner"
    with installation_owner_lock(root):
        assert root.stat().st_mode & 0o777 == 0o700
        assert (root / ".installation-owner").stat().st_mode & 0o777 == 0o600
        with pytest.raises(BlockingIOError), installation_owner_lock(root):
            raise AssertionError("Second owner admitted")
    with installation_owner_lock(root):
        pass


@pytest.mark.parametrize("fault", ["public-root", "root-symlink", "file-symlink", "public-lock"])
def test_owner_storage_must_be_private_and_not_redirected(tmp_path, fault):
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    lock = root / ".installation-owner"
    if fault == "public-root":
        root.chmod(0o755)
    elif fault == "root-symlink":
        link = tmp_path / "redirect"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif fault == "file-symlink":
        target = tmp_path / "other-lock"
        target.touch(mode=0o600)
        lock.symlink_to(target)
    else:
        lock.touch(mode=0o644)
    with pytest.raises((ValueError, OSError)), installation_owner_lock(root):
        raise AssertionError("Unsafe storage admitted")


def test_worker_drains_on_lifespan_and_preserves_failure_as_unresolved(monkeypatch, caplog):
    from cms import participant_control_runtime as runtime

    calls, sent = [], []
    monkeypatch.setattr(runtime, "begin_participant_control_drain", lambda: calls.append("drain"))

    def incomplete():
        calls.append("close")
        raise ValueError("synthetic-private-unresolved-cause")

    monkeypatch.setattr(runtime, "close_participant_control_registry", incomplete)

    async def scenario():
        async def application(*args):
            raise AssertionError("Lifespan reached portal application")

        messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        worker = ParticipantControlApplication(application)
        await worker({"type": "lifespan"}, receive, send)
        assert worker.draining

    asyncio.run(scenario())
    assert calls == ["drain", "close"]
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.failed", "message": "Participant owner drain incomplete"},
    ]
    assert "synthetic-private-unresolved-cause" not in caplog.text + repr(sent)


def test_worker_health_separates_liveness_from_readiness_and_does_not_open_portal(monkeypatch):
    import cms.participant_control_worker as module

    monkeypatch.setattr(module, "_ready", lambda: False)

    async def scenario():
        async def application(*args):
            raise AssertionError("Health reached portal application")

        async def receive():
            return {"type": "http.request", "body": b""}

        worker = ParticipantControlApplication(application)
        for path, expected in [("/health/live", 200), ("/health/ready", 503)]:
            sent = []

            async def send(message, responses=sent):
                responses.append(message)

            await worker({"type": "http", "path": path}, receive, send)
            assert sent[0]["status"] == expected

    asyncio.run(scenario())


def test_shutdown_waits_for_the_bounded_recovery_call_before_releasing_the_owner(monkeypatch):
    from threading import Event

    from cms import participant_control_runtime as runtime
    from cms import participant_control_worker as module

    calls = []
    release = Event()
    monkeypatch.setattr(runtime, "begin_participant_control_drain", lambda: calls.append("drain"))
    monkeypatch.setattr(runtime, "close_participant_control_registry", lambda: calls.append("close"))

    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        shutdown = asyncio.Event()
        sent = []

        def recover(cursor):
            calls.append("recover")
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=5), "Synthetic recovery was not released"
            calls.append("settled")
            return cursor

        monkeypatch.setattr(module, "_recover_one_call", recover)
        first = True

        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "lifespan.startup"}
            await shutdown.wait()
            return {"type": "lifespan.shutdown"}

        async def send(message):
            sent.append(message)

        async def application(*args):
            raise AssertionError("Lifespan reached HTTP")

        worker = ParticipantControlApplication(application)
        task = asyncio.create_task(worker({"type": "lifespan"}, receive, send))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            shutdown.set()
            await asyncio.sleep(0)
            assert "close" not in calls
            release.set()
            await asyncio.wait_for(task, timeout=2)
        finally:
            release.set()
            if not task.done():
                await task
        assert calls == ["recover", "drain", "settled", "close"]
        assert sent[-1]["type"] == "lifespan.shutdown.complete"

    asyncio.run(scenario())


def test_startup_cannot_install_registry_before_its_live_pod_is_verified(installed, monkeypatch, settings):
    from unittest.mock import Mock

    import django

    from cms import participant_control_runtime as runtime
    from cms import participant_control_worker as worker
    from cms import participant_control_worker_identity as identity
    from cms.services import _participant_control_installation as installation
    from shared.cloud.kubernetes import KubernetesTaskRunner
    from tests.shared.cloud.test_kubernetes_task_runner import _profile

    settings.PARTICIPANT_CONTROL_OWNER_PROCESS = True
    settings.CLOUD_PROVIDER = "gcp"
    monkeypatch.setattr("shared.cloud.get_task_runner", lambda: KubernetesTaskRunner(_profile()))
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(installation, "require_native_control_installation", lambda: installed)
    monkeypatch.setattr(
        identity, "installed_owner_address", Mock(side_effect=ValueError("synthetic-private-pod-cause"))
    )
    install = Mock()
    monkeypatch.setattr(runtime, "install_participant_control_registry", install)
    with pytest.raises(SystemExit, match="Participant control worker unavailable") as failure:
        worker.main()
    assert failure.value.__cause__ is None
    install.assert_not_called()
