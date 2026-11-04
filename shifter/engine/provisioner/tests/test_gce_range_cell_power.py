"""Tests for GCE range-cell guest power operations (issue #614)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gce_range_cell_power import run_power_operation


def _clients(status: str) -> SimpleNamespace:
    """Fake GCEClients whose instances.get reports ``status`` after a power op."""
    instances = SimpleNamespace(
        stop=lambda **kwargs: SimpleNamespace(name="op-stop"),
        start=lambda **kwargs: SimpleNamespace(name="op-start"),
        get=lambda **kwargs: SimpleNamespace(
            id="12345",
            status=status,
            disks=[SimpleNamespace(type_="PERSISTENT", source="projects/p/zones/z/disks/root")],
            metadata=SimpleNamespace(items=[]),
            resource_policies=[],
        ),
    )
    op_service = SimpleNamespace(wait=lambda **kwargs: SimpleNamespace(status="DONE"))
    return SimpleNamespace(
        instances=instances,
        zone_operations=op_service,
        region_operations=op_service,
        global_operations=op_service,
    )


# The persisted engine_instance.state shape: gcp_-prefixed output keys are
# nested under provider_metadata.gcp with the prefix removed.
_STATE = {
    "asset_type": "gce_vm",
    "cloud_provider": "gcp",
    "instance_id": "shifter-r-42-victim",
    "provider_metadata": {
        "gcp": {
            "project_id": "test-project",
            "zone": "us-central1-a",
            "instance_name": "shifter-r-42-victim",
        }
    },
}


def test_stop_reaches_terminated():
    # Should not raise when the instance observes TERMINATED after stop.
    run_power_operation("stop", _STATE, clients=_clients("TERMINATED"))


def test_start_reaches_running():
    run_power_operation("start", _STATE, clients=_clients("RUNNING"))


def test_stop_calls_instances_stop_with_target():
    calls = {}

    def stop(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(name="op")

    clients = _clients("TERMINATED")
    clients.instances.stop = stop
    run_power_operation("stop", _STATE, clients=clients)
    assert calls == {"project": "test-project", "zone": "us-central1-a", "instance": "shifter-r-42-victim"}


def test_stop_raises_when_status_not_terminal():
    clients = _clients("RUNNING")
    with pytest.raises(RuntimeError, match="did not reach TERMINATED"):
        run_power_operation("stop", _STATE, clients=clients)


def test_start_raises_when_status_not_running():
    clients = _clients("TERMINATED")
    with pytest.raises(RuntimeError, match="did not reach RUNNING"):
        run_power_operation("start", _STATE, clients=clients)


def test_unknown_operation_raises():
    clients = _clients("RUNNING")
    with pytest.raises(ValueError, match="Unknown GCE range-cell operation"):
        run_power_operation("pause", _STATE, clients=clients)


def test_incomplete_state_raises():
    clients = _clients("TERMINATED")
    with pytest.raises(RuntimeError, match="requires project, zone, and instance name"):
        run_power_operation("stop", {"gcp_zone": "z"}, clients=clients)


def test_instance_id_fallback_for_name():
    calls = {}

    def stop(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(name="op")

    clients = _clients("TERMINATED")
    clients.instances.stop = stop
    state = {"gcp_project_id": "p", "gcp_zone": "z", "instance_id": "fallback-name"}
    run_power_operation("stop", state, clients=clients)
    assert calls["instance"] == "fallback-name"


@pytest.mark.parametrize("operation", ["stop", "start"])
@pytest.mark.parametrize(
    "footprint",
    ["missing-disks", "local-ssd", "scheduled", "managed", "missing-id", "malformed-id", "malformed-metadata"],
)
def test_power_rejects_unqualified_footprint_before_mutation(operation, footprint):
    clients = _clients("TERMINATED" if operation == "stop" else "RUNNING")
    observed = clients.instances.get()
    if footprint == "missing-disks":
        observed.disks = []
    elif footprint == "local-ssd":
        observed.disks.append(SimpleNamespace(type_="SCRATCH", source=""))
    elif footprint == "scheduled":
        observed.resource_policies = ["projects/p/regions/r/resourcePolicies/schedule"]
    elif footprint == "managed":
        observed.metadata.items = [SimpleNamespace(key="created-by", value="instanceGroupManagers/group")]
    elif footprint == "malformed-id":
        observed.id = {"private": "provider-value"}
    elif footprint == "malformed-metadata":
        observed.metadata.items = "not-an-observed-metadata-list"
    else:
        observed.id = ""
    clients.instances.get = lambda **kwargs: observed
    mutations = []
    clients.instances.stop = lambda **kwargs: mutations.append("stop") or SimpleNamespace(name="op")
    clients.instances.start = lambda **kwargs: mutations.append("start") or SimpleNamespace(name="op")

    with pytest.raises(RuntimeError, match="footprint"):
        run_power_operation(operation, _STATE, clients=clients)

    assert mutations == []


def test_power_rejects_replaced_instance_in_readback():
    clients = _clients("TERMINATED")
    original = clients.instances.get()
    replacement = SimpleNamespace(**{**vars(original), "id": "67890"})
    observations = iter([original, replacement])
    clients.instances.get = lambda **kwargs: next(observations)

    with pytest.raises(RuntimeError, match="identity"):
        run_power_operation("stop", _STATE, clients=clients)


def test_power_checks_discovery_client_response_shape():
    clients = _clients("RUNNING")
    clients.instances.get = lambda **kwargs: {
        "id": "12345",
        "status": "RUNNING",
        "disks": [{"type": "PERSISTENT", "source": "projects/p/zones/z/disks/root"}],
        "metadata": {"items": []},
        "resourcePolicies": [],
    }

    run_power_operation("start", _STATE, clients=clients)


def test_power_rejects_disk_replacement_in_readback():
    clients = _clients("TERMINATED")
    original = clients.instances.get()
    replacement = SimpleNamespace(
        **{**vars(original), "disks": [SimpleNamespace(type_="PERSISTENT", source="projects/p/zones/z/disks/other")]}
    )
    observations = iter([original, replacement])
    clients.instances.get = lambda **kwargs: next(observations)

    with pytest.raises(RuntimeError, match="persistent disks"):
        run_power_operation("stop", _STATE, clients=clients)


def test_power_rechecks_the_footprint_admitted_for_the_whole_range():
    clients = _clients("TERMINATED")
    mutations = []
    clients.instances.stop = lambda **kwargs: mutations.append("stop") or SimpleNamespace(name="stop")

    with pytest.raises(RuntimeError, match="changed after range admission"):
        run_power_operation(
            "stop",
            _STATE,
            clients=clients,
            expected_footprint=("67890", ("projects/p/zones/z/disks/root",)),
        )

    assert mutations == []
