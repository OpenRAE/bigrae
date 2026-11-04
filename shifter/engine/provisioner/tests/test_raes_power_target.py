"""Realized GCE addressing survives the closed native member result boundary."""

import pytest
from shared.operation_results import OperationResultError, ResultStep, parse_result_payload

from raes_range_members import realized_members


def _instance():
    return {
        "uuid": "provision.node.web#0",
        "name": "web",
        "os": "linux",
        "private_ip": "10.0.0.3",
        "instance_id": "synthetic-web",
        "subnet_name": "lan",
        "participant_access_channels": [],
        "participant_access_usernames": {},
        "gcp_project_id": "synthetic-project",
        "gcp_zone": "europe-west3-a",
        "gcp_instance_name": "synthetic-web",
        "bootstrap_capability": "standard",
        "native_power_incarnation": {
            "instance_identity": "123",
            "disks": [{"name": "synthetic-boot", "identity": "456"}],
        },
    }


def _parse(members):
    return parse_result_payload(
        "raes-range",
        "provision",
        step=ResultStep.RAES_TERMINAL_READY,
        payload={"raes_status": "succeeded", "members": members},
    )["members"]


def test_native_power_target_crosses_the_actual_producer_and_parser():
    members = realized_members({"instances": [_instance()]})
    parsed = _parse(members)
    assert parsed[0]["native_power_target"] == {
        "backend": "gce",
        "project_id": "synthetic-project",
        "zone": "europe-west3-a",
        "instance_name": "synthetic-web",
        "bootstrap_capability": "standard",
    }
    assert parsed[0]["native_power_incarnation"] == _instance()["native_power_incarnation"]


def test_location_without_incarnation_remains_unqualified():
    instance = _instance()
    del instance["native_power_incarnation"]
    parsed = _parse(realized_members({"instances": [instance]}))
    assert "native_power_incarnation" not in parsed[0]


@pytest.mark.parametrize("change", ["partial", "extra", "private-response", "wrong-instance", "wrong-backend"])
def test_native_power_target_refuses_unbounded_or_inconsistent_input(change):
    members = realized_members({"instances": [_instance()]})
    target = {
        "backend": "gce",
        "project_id": "synthetic-project",
        "zone": "europe-west3-a",
        "instance_name": "synthetic-web",
        "bootstrap_capability": "standard",
    }
    members[0]["native_power_target"] = target
    if change == "partial":
        del target["zone"]
    elif change == "extra":
        target["sdk_response"] = {"private": "data"}
    elif change == "private-response":
        target["project_id"] = "private\nprovider response"
    elif change == "wrong-instance":
        target["instance_name"] = "another-web"
    else:
        target["backend"] = "ec2"
    with pytest.raises(OperationResultError):
        _parse(members)
