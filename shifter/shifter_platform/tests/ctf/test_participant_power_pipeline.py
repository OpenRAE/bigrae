"""One generation traverses authenticated review, native launch, TLS invocation and real SQL results.

Only external Kubernetes and Compute wire responses are synthetic. The actual
provisioner CLI runs in its own environment and uses the production input reader,
private HTTPS client, GCE power helper, and result writer.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from socketserver import ThreadingMixIn
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import UUID, uuid4
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.handlers.wsgi import WSGIHandler
from django.db import connection, connections
from rest_framework.test import APIClient

from tests.cms.conftest import make_pack
from tests.cms.test_participant_control_binding import controlled_pack, controlled_source, product_range, tenant
from tests.ctf.test_participant_control_api import bind
from tests.shared.cloud.test_gcp_task_runner import _ApiException as ApiException
from tests.shared.cloud.test_gcp_task_runner import _make_fake_k8s_client
from tests.shared.raes.test_native_power_conformance import assert_native_control_records_conform

__all__ = ["controlled_pack", "controlled_source", "make_pack", "product_range", "tenant"]
pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
_ROOT = Path(__file__).resolve().parents[4]
_PUBLIC = "/api/v1/participant-control/ctf"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        """Never retain request or authentication material in test server logs."""


class _ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _tls_material(directory, host):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Synthetic native control test CA")])
    now = datetime.now(UTC)
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path, key_path = directory / "server.pem", directory / "server.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    key_path.chmod(0o600)
    return ca.public_bytes(serialization.Encoding.PEM).decode(), cert_path, key_path


@pytest.fixture
def live_worker(product_range, settings, tmp_path, monkeypatch):
    from cms.participant_control_runtime import close_participant_control_registry, install_participant_control_registry
    from cms.services._participant_control_registry import NativeParticipantControlRegistry
    from engine.ecs._env import _GCP_PROVISIONER_ENV_KEYS
    from shared.participant_control_installation import NativeControlInstallation

    assert connection.vendor == "postgresql"
    original = settings.PARTICIPANT_CONTROL_INSTALLATION
    host = f"participant-control.{original.namespace}.svc"
    ca, certificate, key = _tls_material(tmp_path, host)
    installed = NativeControlInstallation.model_validate({**original.model_dump(), "trust_ca_pem": ca})
    settings.PARTICIPANT_CONTROL_INSTALLATION = installed
    # Build the real launcher environment exclusively from this synthetic installation.
    for name in _GCP_PROVISIONER_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PARTICIPANT_CONTROL_CONFIGURATION", installed.model_dump_json())
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("DB_AUTH_MODE", "password")
    for name in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.setenv("PROVISIONER_DB_" + name, str(connection.settings_dict[name]))
    settings.PARTICIPANT_CONTROL_ENABLED = True
    settings.PARTICIPANT_CONTROL_OWNER_PROCESS = True
    settings.ROOT_URLCONF = "config.participant_control_worker_urls"
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, host]
    settings.SECURE_SSL_REDIRECT = False
    settings.CLOUD_PROVIDER = "gcp"
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "synthetic-native-provisioner"
    install_participant_control_registry(NativeParticipantControlRegistry(installed, store_root=tmp_path / "runtime"))
    server = make_server("127.0.0.1", 0, WSGIHandler(), server_class=_ThreadedServer, handler_class=_QuietHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield NS(item=product_range, installed=installed, port=server.server_port, directory=tmp_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        close_participant_control_registry()
        connections.close_all()


def _kubernetes(monkeypatch, settings):
    from shared.cloud.gcp.task_runner import GCPTaskRunner

    kube = _make_fake_k8s_client()
    jobs, pods = {}, {}
    batch, core, auth = Mock(), Mock(), Mock()

    def read_job(name, namespace, **kwargs):
        if (namespace, name) not in jobs:
            raise ApiException(status=404)
        return jobs[namespace, name]

    def create_job(namespace, body, **kwargs):
        body.metadata.namespace = namespace
        body.metadata.uid = "synthetic-native-job"
        body.metadata.deletion_timestamp = None
        body.status = NS(active=1, succeeded=0, failed=0)
        jobs[namespace, body.metadata.name] = body
        container = body.spec.template.spec.containers[0]
        pods[namespace, "synthetic-native-pod"] = NS(
            metadata=kube.V1ObjectMeta(
                name="synthetic-native-pod",
                namespace=namespace,
                uid="synthetic-native-pod-uid",
                deletion_timestamp=None,
                owner_references=[
                    kube.V1OwnerReference(
                        api_version="batch/v1",
                        kind="Job",
                        name=body.metadata.name,
                        uid=body.metadata.uid,
                        controller=True,
                    )
                ],
            ),
            spec=deepcopy(body.spec.template.spec),
            status=NS(
                phase="Running",
                container_statuses=[
                    NS(
                        name=container.name,
                        image=container.image,
                        image_id=container.image,
                        container_id="containerd://synthetic-native",
                        ready=True,
                        restart_count=0,
                        state=NS(running=NS()),
                    )
                ],
            ),
        )
        return body

    def token_review(body, **kwargs):
        assert body["spec"]["token"] == "synthetic.native.bound.token"
        assert body["spec"]["audiences"] == ["shifter-native-participant-invocation"]
        namespace = settings.ENGINE_TASK_CLUSTER
        return NS(
            status=NS(
                authenticated=True,
                error=None,
                audiences=body["spec"]["audiences"],
                user=NS(
                    username=f"system:serviceaccount:{namespace}:{settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME}",
                    uid="synthetic-native-ksa",
                    extra={
                        "authentication.kubernetes.io/pod-name": ["synthetic-native-pod"],
                        "authentication.kubernetes.io/pod-uid": ["synthetic-native-pod-uid"],
                    },
                ),
            )
        )

    batch.read_namespaced_job.side_effect = read_job
    batch.create_namespaced_job.side_effect = create_job
    core.read_namespaced_pod.side_effect = lambda name, namespace, **kwargs: pods[namespace, name]
    auth.create_token_review.side_effect = token_review
    kube.AuthenticationV1Api = lambda **kwargs: auth
    runner = GCPTaskRunner()
    monkeypatch.setattr(runner, "_load_kubernetes_api", lambda: (batch, core, kube, ApiException))
    monkeypatch.setattr("shared.cloud.get_task_runner", lambda: runner)
    monkeypatch.setattr("engine.ecs.get_task_runner", lambda: runner)
    return NS(batch=batch, core=core, jobs=jobs)


def _reviewed_pause(worker):
    human = APIClient()
    human.force_login(worker.item.case.actor)
    view = bind(human, worker.item).json()
    proposal, action = uuid4(), uuid4()
    for kind in ("proposal", "approval", "action"):
        current = human.get(f"{_PUBLIC}/bindings/{view['binding_id']}/")
        assert current.status_code == 200, current.json()
        receipt = human.post(
            f"{_PUBLIC}/bindings/{view['binding_id']}/commands/",
            {
                "request_id": str(proposal if kind == "proposal" else action if kind == "action" else uuid4()),
                "kind": kind,
                "verb": "pause",
                "proposal_id": str(proposal),
                "action_id": str(action),
                "expected_cut_digest": current.json()["control_cut_digest"],
            },
            format="json",
        )
        assert receipt.status_code == 200, receipt.json()
        assert receipt.json()["state"] == "succeeded"
    return human, UUID(view["binding_id"]), action, UUID(receipt.json()["operation_id"])


def _execute_cli(worker, job, secrets):
    directory = worker.directory
    token, report = directory / "bound-token", directory / "provider-report.json"
    token.write_text("synthetic.native.bound.token")
    token.chmod(0o600)
    database = connection.settings_dict
    assert str(database["NAME"]).startswith("test_")
    provisioner = _ROOT / "shifter/engine/provisioner"
    secret_values = {secret.metadata.name: secret.string_data for secret in secrets}
    environment = {}
    for entry in job.spec.template.spec.containers[0].env:
        value = getattr(entry, "value", None)
        if value is None:
            reference = entry.value_from.secret_key_ref
            value = secret_values[reference.name][reference.key]
        environment[entry.name] = value
    assert environment["DB_NAME"] == str(database["NAME"])
    assert environment["PARTICIPANT_CONTROL_CONFIGURATION"] == worker.installed.model_dump_json()
    environment.update(
        {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(provisioner),
            "NATIVE_CONTROL_TEST_PORT": str(worker.port),
            "NATIVE_CONTROL_TEST_TOKEN": str(token),
            "NATIVE_CONTROL_TEST_REPORT": str(report),
        }
    )
    command = job.spec.template.spec.containers[0].args
    uv = shutil.which("uv")
    assert uv is not None
    result = subprocess.run(  # noqa: S603  # fixed provisioner entrypoint and immutable native outbox argv
        [uv, "run", "--locked", "python", "tests/fixtures/native_power_pipeline.py", *command],
        cwd=provisioner,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert report.exists(), f"Provisioner did not reach the native dispatch: exit={result.returncode}"
    return result.returncode, json.loads(report.read_text())


@pytest.mark.parametrize("revoked", [False, True])
def test_authenticated_review_through_provisioner_tls_effect_readback_results_and_conformance(
    live_worker, settings, monkeypatch, revoked
):
    from cms.participant_control_runtime import participant_control_registry
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from engine.models import (
        OperationInput,
        OperationResultDisposition,
        OperationResultInbox,
        ParticipantPowerInvocation,
        ParticipantPowerReservation,
    )
    from engine.services import apply_pending_operation_results
    from shared.models import AuditLog

    worker = live_worker
    kube_wire = _kubernetes(monkeypatch, settings)
    human, binding, action, portable_operation = _reviewed_pause(worker)
    reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action)
    generation = worker.item.case.row.resource_generation
    intent = reservation.launch_intent
    assert OperationInput.objects.get(operation_id=intent.operation_id).contract_version == "2"
    assert reservation.portable_operation_uuid == portable_operation and reservation.released_at is not None
    launcher = Command()
    claimed = launcher._claim_next(intent_id=intent.intent_id)
    assert claimed is not None
    launcher._launch(claimed)
    intent.refresh_from_db()
    assert intent.status == "SUCCEEDED", intent.last_error
    assert kube_wire.batch.create_namespaced_job.call_count == 1
    job = next(iter(kube_wire.jobs.values()))
    assert job.spec.active_deadline_seconds == 1800
    if revoked:
        worker.item.case.actor.policy_principals.clear()
    exit_code, provider = _execute_cli(
        worker, job, [call.kwargs["body"] for call in kube_wire.core.create_namespaced_secret.call_args_list]
    )
    apply_pending_operation_results()
    worker.item.case.row.refresh_from_db()
    assert worker.item.case.row.resource_generation == generation
    assert (provider["instance_identity"], provider["disk_identity"]) == ("123", "456")
    if revoked:
        assert exit_code != 0 and provider["effects"] == [] and provider["status"] == "RUNNING"
        assert worker.item.case.row.status == "failed"
        assert not ParticipantPowerInvocation.objects.filter(permission_issued=True).exists()
        return
    assert exit_code == 0 and provider["status"] == "TERMINATED"
    assert len(provider["effects"]) == 1 and len(provider["reads"]) >= 6
    grant = ParticipantPowerInvocation.objects.get(reservation=reservation)
    assert provider["effects"][0]["request_id"] == str(grant.invocation_id)
    assert provider["effects"][0]["retry"] is None and provider["effects"][0]["timeout"] == 10.0
    assert grant.permission_issued and grant.closed_at is not None
    assert worker.item.case.row.status == "paused"
    results = list(OperationResultInbox.objects.filter(operation_id=intent.operation_id))
    assert len(results) == 2 and all(row.disposition == OperationResultDisposition.APPLIED for row in results)
    assert all(row.contract_version == "1" for row in results)
    admission_audit = AuditLog.objects.filter(
        new_state__native_invocation=str(grant.invocation_id),
    ).earliest("timestamp")
    assert admission_audit.timestamp <= datetime.fromisoformat(provider["effects"][0]["started_at"])
    assert AuditLog.objects.filter(new_state__participant_control_command=str(action)).exists()
    with participant_control_registry().lease(worker.item.case.credential, binding) as owner:
        assert_native_control_records_conform(owner.session)
    state = human.get(f"{_PUBLIC}/bindings/{binding}/")
    assert state.status_code == 200 and state.json()["range_status"] == "paused"
