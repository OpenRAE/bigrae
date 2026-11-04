"""The native provisioner probes admitted hosts without exporting management data."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncssh
import pytest

import worker_host_observation as subject
from tests.test_range_management_projection import output


@pytest.fixture
def peers(monkeypatch):
    key = asyncssh.generate_private_key("ssh-ed25519")
    result = output()
    instance = result["instances"][0]
    instance.update(
        asset_type="gce_vm",
        gcp_project_id="synthetic-project",
        gcp_zone="us-central1-a",
        gcp_instance_name="synthetic-vm",
        gcp_host_public_key=key.export_public_key().decode(),
    )
    reads = []
    numeric = SimpleNamespace(name="synthetic-vm", id=12345)

    def get(**kwargs):
        reads.append(kwargs)
        return numeric

    monkeypatch.setattr(subject, "_build_clients", lambda: SimpleNamespace(instances=SimpleNamespace(get=get)))
    secrets = []

    def secret(ref):
        secrets.append(ref)
        return key.export_private_key().decode()

    monkeypatch.setattr(subject.GCPSecretsStore, "get_secret", secret)
    seen = []
    payload = {"machine_id": "a" * 32, "daemon_id": "b" * 36, "docker_version": "29.1.3", "daemon_count": 1}

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create_process(self, command):
            assert command == "sudo -n python3 -"
            return SimpleNamespace(
                stdout=SimpleNamespace(read=AsyncMock(side_effect=[json.dumps(payload), ""])),
                stderr=SimpleNamespace(read=AsyncMock(return_value="")),
                stdin=SimpleNamespace(write=seen.append, write_eof=lambda: None),
                wait_closed=AsyncMock(),
                exit_status=0,
                close=lambda: None,
            )

    def connect(host, **kwargs):
        assert host == "10.1.0.2"
        assert kwargs["known_hosts"] is not None
        assert kwargs["client_keys"]
        return Connection()

    monkeypatch.setattr(asyncssh, "connect", connect)
    return SimpleNamespace(
        result=result, instance=instance, reads=reads, numeric=numeric, secrets=secrets, seen=seen, payload=payload
    )


def test_provisioner_returns_only_bounded_host_facts(peers):
    from shared.operation_results import ResultStep, parse_result_payload

    fragment = subject.worker_observations_fragment(peers.result, ("provision.node.host",))
    safe = fragment["worker_observations"]["provision.node.host#0"]
    assert safe["daemon_count"] == 1 and safe["docker_version"] == "29.1.3"
    assert peers.reads == [{"project": "synthetic-project", "zone": "us-central1-a", "instance": "synthetic-vm"}]
    assert peers.secrets and peers.seen == [subject._PROBE]
    assert "unix:///var/run/docker.sock" in peers.seen[0]
    assert all(safe[field].startswith("sha256:") for field in ("vm_identity", "machine_identity", "daemon_identity"))
    assert "a" * 32 not in str(fragment) and "management-only" not in str(fragment)
    parsed = parse_result_payload(
        "raes-range",
        "provision",
        step=ResultStep.RAES_TERMINAL_READY,
        payload={"raes_status": "succeeded", "members": [], **fragment},
    )
    assert parsed["worker_observations"] == fragment["worker_observations"]


def test_reused_vm_name_does_not_reuse_vm_identity(peers):
    first = subject.worker_observations_fragment(peers.result, ("provision.node.host",))
    peers.numeric.id = 67890
    second = subject.worker_observations_fragment(peers.result, ("provision.node.host",))
    assert (
        first["worker_observations"]["provision.node.host#0"]["vm_identity"]
        != second["worker_observations"]["provision.node.host#0"]["vm_identity"]
    )


@pytest.mark.parametrize("change", ["public-ip", "loopback", "missing-key", "provider-id", "provider-name", "backend"])
def test_invalid_host_is_refused_before_secret_read(peers, change):
    if change in {"public-ip", "loopback"}:
        peers.instance["private_ip"] = "8.8.8.8" if change == "public-ip" else "127.0.0.1"
    elif change == "missing-key":
        peers.instance["gcp_host_public_key"] = ""
    elif change == "provider-id":
        peers.numeric.id = "synthetic-vm"
    elif change == "provider-name":
        peers.numeric.name = "another-vm"
    else:
        peers.instance["asset_type"] = "ec2_vm"
    with pytest.raises(ValueError):
        subject.worker_observations_fragment(peers.result, ("provision.node.host",))
    assert not peers.secrets


@pytest.mark.parametrize(
    "change",
    [
        {"daemon_count": 2},
        {"daemon_count": True},
        {"machine_id": "bad"},
        {"docker_version": "a" * 1000},
        {"secret": "extra"},
    ],
)
def test_invalid_guest_facts_cannot_produce_success(peers, change):
    peers.payload.update(change)
    with pytest.raises(ValueError):
        subject.worker_observations_fragment(peers.result, ("provision.node.host",))


def test_ordinary_range_has_no_probe_or_provider_read(peers):
    assert subject.worker_observations_fragment(peers.result, ()) == {}
    assert not peers.secrets and not peers.reads


def test_invalid_observation_errors_do_not_echo_guest_or_access_material():
    from shared.worker_observations import validate_worker_observations

    with pytest.raises(ValueError) as error:
        validate_worker_observations({"host#0": {"private_material": "untrusted-value-must-not-escape"}})
    assert str(error.value) == "Worker observations are invalid"
