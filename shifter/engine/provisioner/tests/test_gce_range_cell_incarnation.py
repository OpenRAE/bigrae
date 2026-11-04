"""Power qualification observes VM and disk identities through fixed Compute clients."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from shared.exceptions import ValidationError
from shared.native_power import parse_gce_power_incarnation, parse_gce_power_target

_PREFIX = "https://www.googleapis.com/compute/v1/projects/synthetic-project/zones/europe-west3-a"
_INVOCATION = UUID("a3ed9365-fddd-487a-a1e7-a6ed70e6aee0")
_TARGET = {
    "backend": "gce",
    "project_id": "synthetic-project",
    "zone": "europe-west3-a",
    "instance_name": "synthetic-web",
    "bootstrap_capability": "standard",
}


def _observations():
    instance = {
        "id": "123",
        "disks": [{"type": "PERSISTENT", "source": f"{_PREFIX}/disks/synthetic-boot"}],
        "metadata": {"items": []},
    }
    disk = {"id": "456", "users": [f"{_PREFIX}/instances/synthetic-web"]}
    return instance, disk


def _clients(instance, disk, calls):
    def read_instance(**kwargs):
        calls.append(("instance", kwargs))
        return instance

    def read_disk(**kwargs):
        calls.append(("disk", kwargs))
        return disk

    return SimpleNamespace(
        instances=SimpleNamespace(get=read_instance),
        disks=SimpleNamespace(get=read_disk),
    )


def test_observes_original_vm_and_dedicated_disk_incarnations():
    from gce_range_cell_incarnation import observe_power_incarnation

    instance, disk = _observations()
    calls = []
    result = observe_power_incarnation(
        parse_gce_power_target(_TARGET, instance_id="synthetic-web"),
        clients=_clients(instance, disk, calls),
    )
    assert result.to_transport() == {
        "instance_identity": "123",
        "disks": [{"name": "synthetic-boot", "identity": "456"}],
    }
    assert calls[1] == (
        "disk",
        {
            "project": "synthetic-project",
            "zone": "europe-west3-a",
            "disk": "synthetic-boot",
            "timeout": 10.0,
            "retry": None,
        },
    )
    assert all(0 < call[1]["timeout"] <= 10.0 and call[1]["retry"] is None for call in calls)
    assert len(calls) == 3


def test_expired_observation_budget_performs_no_provider_reads():
    from gce_range_cell_incarnation import observe_power_incarnation

    instance, disk = _observations()
    calls = []
    with pytest.raises(TimeoutError, match="observation budget"):
        observe_power_incarnation(
            parse_gce_power_target(_TARGET, instance_id="synthetic-web"),
            clients=_clients(instance, disk, calls),
            deadline=0,
        )
    assert calls == []


@pytest.mark.parametrize(
    "fault", ["vm-identity", "disk-identity", "shared", "unobserved-users", "regional", "foreign", "url"]
)
def test_unqualified_incarnations_are_refused_without_effects(fault):
    from gce_range_cell_incarnation import observe_power_incarnation

    instance, disk = _observations()
    if fault == "vm-identity":
        instance["id"] = "not-an-identity"
    elif fault == "disk-identity":
        disk["id"] = None
    elif fault == "shared":
        disk["users"].append(f"{_PREFIX}/instances/another-web")
    elif fault == "unobserved-users":
        del disk["users"]
    elif fault == "regional":
        instance["disks"][0]["source"] = "projects/synthetic-project/regions/europe-west3/disks/synthetic-boot"
    elif fault == "foreign":
        instance["disks"][0]["source"] = f"{_PREFIX}/disks/synthetic-boot".replace(
            "synthetic-project", "foreign-project"
        )
    else:
        instance["disks"][0]["source"] = "https://unapproved.invalid/private-response"
    with pytest.raises((RuntimeError, ValidationError)):
        observe_power_incarnation(
            parse_gce_power_target(_TARGET, instance_id="synthetic-web"),
            clients=_clients(instance, disk, []),
        )


def test_failed_optional_qualification_removes_old_and_partial_claims(caplog):
    from gce_range_cell_incarnation import retain_power_incarnations

    instance, disk = _observations()
    outputs = [
        {
            "instance_id": "synthetic-web",
            "gcp_project_id": "synthetic-project",
            "gcp_zone": "europe-west3-a",
            "gcp_instance_name": "synthetic-web",
            "bootstrap_capability": "standard",
            "native_power_incarnation": {"private": "stale-qualification"},
        }
    ]
    disk["id"] = "private-provider-response"
    retain_power_incarnations(outputs, clients=_clients(instance, disk, []))
    assert "native_power_incarnation" not in outputs[0]
    assert "private-provider-response" not in caplog.text
    assert "stale-qualification" not in caplog.text


def _native_power_state():
    return {
        "gcp_project_id": _TARGET["project_id"],
        "gcp_zone": _TARGET["zone"],
        "gcp_instance_name": _TARGET["instance_name"],
        "native_power_target": dict(_TARGET),
    }


def _retained_incarnation():
    return parse_gce_power_incarnation(
        {
            "instance_identity": "123",
            "disks": [{"name": "synthetic-boot", "identity": "456"}],
        }
    )


def _power_clients(instance, disk, calls, *, after_mutation=None):
    clients = _clients(instance, disk, calls)
    clients.mutation_kwargs = []

    def mutate(verb, **kwargs):
        calls.append(("mutation", verb))
        clients.mutation_kwargs.append(kwargs)
        instance["status"] = "TERMINATED" if verb == "stop" else "RUNNING"
        if after_mutation is not None:
            after_mutation()
        return SimpleNamespace(name="synthetic-operation")

    clients.instances.stop = lambda **kwargs: mutate("stop", **kwargs)
    clients.instances.start = lambda **kwargs: mutate("start", **kwargs)
    clients.zone_operations = SimpleNamespace(wait=lambda **kwargs: SimpleNamespace(status="DONE"))
    return clients


@pytest.mark.parametrize("verb", ["stop", "start"])
def test_pinned_native_power_rechecks_identities_then_fences_immediately_before_invocation(verb):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    calls = []
    clients = _power_clients(instance, disk, calls)
    run_power_operation(
        verb,
        _native_power_state(),
        clients=clients,
        expected_incarnation=_retained_incarnation(),
        invocation_id=_INVOCATION,
        before_invoke=lambda: calls.append(("guard", None)),
    )
    mutation = calls.index(("mutation", verb))
    assert calls[mutation - 1] == ("guard", None)
    assert sum(call[0] == "mutation" for call in calls) == 1
    assert sum(call[0] == "disk" for call in calls) == 2
    assert all(
        call[1].get("retry", "missing") is None and 0 < call[1].get("timeout", 0) <= 10.0
        for call in calls
        if call[0] == "instance"
    )
    assert clients.mutation_kwargs == [
        {
            "project": _TARGET["project_id"],
            "zone": _TARGET["zone"],
            "instance": _TARGET["instance_name"],
            "request_id": str(_INVOCATION),
            "retry": None,
            "timeout": 10.0,
        }
    ]


@pytest.mark.parametrize("verb", ["stop", "start"])
def test_native_power_requires_a_durable_invocation_identity(verb):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    calls = []
    with pytest.raises(RuntimeError, match="invocation identity"):
        run_power_operation(
            verb,
            _native_power_state(),
            clients=_power_clients(instance, disk, calls),
            expected_incarnation=_retained_incarnation(),
            before_invoke=lambda: None,
        )
    assert calls == []


@pytest.mark.parametrize("verb", ["stop", "start"])
@pytest.mark.parametrize("resource", ["vm", "disk"])
def test_reused_resource_names_cannot_authorize_native_power(verb, resource):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    (instance if resource == "vm" else disk)["id"] = "999"
    calls = []
    with pytest.raises(RuntimeError, match="incarnation changed"):
        run_power_operation(
            verb,
            _native_power_state(),
            clients=_power_clients(instance, disk, calls),
            expected_incarnation=_retained_incarnation(),
            invocation_id=_INVOCATION,
            before_invoke=lambda: calls.append(("guard", None)),
        )
    assert not any(call[0] in {"mutation", "guard"} for call in calls)


@pytest.mark.parametrize("verb", ["stop", "start"])
def test_native_power_has_no_unfenced_fallback(verb):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    calls = []
    with pytest.raises(RuntimeError, match="requires current authority"):
        run_power_operation(
            verb,
            _native_power_state(),
            clients=_power_clients(instance, disk, calls),
            expected_incarnation=_retained_incarnation(),
            invocation_id=_INVOCATION,
        )
    assert calls == []


@pytest.mark.parametrize("verb", ["stop", "start"])
def test_revoked_invocation_authority_prevents_the_provider_call(verb):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    calls = []

    def revoked():
        raise PermissionError("Synthetic authority revoked")

    with pytest.raises(PermissionError, match="authority revoked"):
        run_power_operation(
            verb,
            _native_power_state(),
            clients=_power_clients(instance, disk, calls),
            expected_incarnation=_retained_incarnation(),
            invocation_id=_INVOCATION,
            before_invoke=revoked,
        )
    assert not any(call[0] == "mutation" for call in calls)


@pytest.mark.parametrize("verb", ["stop", "start"])
@pytest.mark.parametrize("resource", ["vm", "disk"])
def test_post_invocation_replacement_is_failed_readback(verb, resource):
    from gce_range_cell_power import run_power_operation

    instance, disk = _observations()
    calls = []

    def replace_resource():
        (instance if resource == "vm" else disk)["id"] = "999"

    with pytest.raises(RuntimeError, match="changed"):
        run_power_operation(
            verb,
            _native_power_state(),
            clients=_power_clients(instance, disk, calls, after_mutation=replace_resource),
            expected_incarnation=_retained_incarnation(),
            invocation_id=_INVOCATION,
            before_invoke=lambda: None,
        )
    assert sum(call[0] == "mutation" for call in calls) == 1
