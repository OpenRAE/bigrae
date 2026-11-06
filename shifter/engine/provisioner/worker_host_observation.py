"""Fixed worker host probe inside the existing provisioner credential boundary."""

from datetime import UTC, datetime
from ipaddress import ip_address
from typing import cast

from shared.guest_probe import GuestProbeRequest, run_guest_probe
from shared.worker_observations import validate_worker_observations
from shifter_adapter_sdk.runtime import canonical_digest, decode_message

from cloud.gcp.secrets import GCPSecretsStore
from gcp_range_cell_clients import _build_clients
from raes_range_members import realized_management
from raes_substrate_observation import observe_gce_worker_identity

_PROBE = """import json, pathlib, subprocess
command = ["docker", "--host", "unix:///var/run/docker.sock", "info", "--format", "{{json .}}"]
info = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
daemon = json.loads(info.stdout)
count = subprocess.run(["pgrep", "-xc", "dockerd"], check=True, capture_output=True, text=True, timeout=5)
print(json.dumps({
    "machine_id": pathlib.Path("/etc/machine-id").read_text().strip(),
    "daemon_id": daemon["ID"], "docker_version": daemon["ServerVersion"], "daemon_count": int(count.stdout),
}))
"""


def _guest_identity(value: object) -> str:
    """Reject oversized or executable guest identity data before hashing it."""
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= 128
        or not value.isascii()
        or not all(character.isalnum() or character in "-:" for character in value)
    ):
        raise ValueError("Worker identity is invalid")
    return value


def worker_observations_fragment(result: dict[str, object], targets: tuple[str, ...]) -> dict[str, object]:
    """Probe only explicitly admitted single-host targets; publish no access data."""
    if not targets:
        return {}
    access = realized_management(result, targets)
    instances = cast(list[dict[str, object]], result["instances"])
    observations = {}
    clients = _build_clients()
    for instance in instances:
        member = str(instance["uuid"])
        if member not in access:
            continue
        host = str(instance.get("private_ip", ""))
        address = ip_address(host)
        if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
            raise ValueError("Worker management address is not private")
        if instance.get("asset_type") != "gce_vm" or instance.get("os") != "linux":
            raise ValueError("Worker host observation backend is unsupported")
        vm = observe_gce_worker_identity(instance, clients)
        binding = access[member]
        output = run_guest_probe(
            GuestProbeRequest(
                host=host,
                username=binding["username"],
                port=binding["port"],
                private_key=GCPSecretsStore.get_secret(str(binding["ssh_key_secret_ref"])),
                host_public_key=binding["host_public_key"],
                command="sudo -n python3 -",
                stdin=_PROBE,
                timeout_s=30,
                max_output_bytes=4096,
            )
        )
        observations[member] = _safe_observation(output, vm)
    return {"worker_observations": validate_worker_observations(observations)}


def _safe_observation(output: str, vm: dict[str, str]) -> dict[str, object]:
    """Discard raw guest identities and reject any unexpected probe response."""
    payload = decode_message(output, limit=4096)
    if not isinstance(payload, dict) or set(payload) != {"machine_id", "daemon_id", "docker_version", "daemon_count"}:
        raise ValueError("Worker host observation failed")
    return {
        "vm_identity": canonical_digest(vm),
        "machine_identity": canonical_digest(_guest_identity(payload["machine_id"])),
        "daemon_identity": canonical_digest(_guest_identity(payload["daemon_id"])),
        "docker_version": payload["docker_version"],
        "daemon_count": payload["daemon_count"],
        "observed_at": datetime.now(UTC).isoformat(),
    }
