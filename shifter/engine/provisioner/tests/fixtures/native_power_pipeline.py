"""Run the real provisioner CLI against synthetic external Compute and mounted-token edges."""

from __future__ import annotations

import json
import os
import runpy
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

_PROVISIONER = Path(__file__).resolve().parents[2]
_SHIFTER = _PROVISIONER.parents[1]
sys.path[:0] = [str(_PROVISIONER), str(_SHIFTER), str(_SHIFTER / "shifter_platform")]


def main() -> None:
    """Keep native dispatch, SQL input/results, TLS transport, and power readback real."""
    from shared.participant_control_installation import NativeControlInstallation

    import native_power_control_client
    import native_power_ops
    from tests.test_gce_range_cell_incarnation import _clients, _observations

    installation = NativeControlInstallation.model_validate_json(os.environ["PARTICIPANT_CONTROL_CONFIGURATION"])
    original_connect = socket.create_connection
    fixed_host = f"participant-control.{installation.namespace}.svc"
    port = int(os.environ["NATIVE_CONTROL_TEST_PORT"])

    def connect(address, *args, **kwargs):
        # Only the test's TCP destination changes. HTTPS still verifies the
        # production fixed hostname, port, public CA and original Host header.
        if address == (fixed_host, 8445):
            address = ("127.0.0.1", port)
        return original_connect(address, *args, **kwargs)

    socket.create_connection = connect
    native_power_control_client._TOKEN_PATH = Path(os.environ["NATIVE_CONTROL_TEST_TOKEN"])
    instance, disk = _observations()
    instance["status"] = "RUNNING"
    reads = []
    effects = []
    clients = _clients(instance, disk, reads)

    def stop(**kwargs):
        effects.append({"started_at": datetime.now(UTC).isoformat(), **kwargs})
        instance["status"] = "TERMINATED"
        return SimpleNamespace(name="synthetic-power-operation")

    clients.instances.stop = stop
    clients.zone_operations = SimpleNamespace(wait=lambda **kwargs: SimpleNamespace(status="DONE"))
    native_power_ops._build_clients = lambda: clients
    original_argv = sys.argv[1:]
    try:
        sys.argv = [str(_PROVISIONER / "main.py"), *original_argv]
        runpy.run_path(str(_PROVISIONER / "main.py"), run_name="__main__")
    finally:
        Path(os.environ["NATIVE_CONTROL_TEST_REPORT"]).write_text(
            json.dumps(
                {
                    "status": instance["status"],
                    "instance_identity": instance["id"],
                    "disk_identity": disk["id"],
                    "reads": reads,
                    "effects": effects,
                }
            )
        )


if __name__ == "__main__":
    main()
