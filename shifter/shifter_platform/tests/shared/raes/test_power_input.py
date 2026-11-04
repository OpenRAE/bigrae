"""Native lifecycle input binds complete compiled membership to realized GCE targets."""

from uuid import uuid4

import pytest

from shared.exceptions import ValidationError
from shared.raes.power_input import build_native_power_input, parse_native_power_input


def _plan():
    return {
        "kind": "raes_provisioning_plan",
        "resources": {
            "provision.node.web": {
                "address": "provision.node.web",
                "resource_type": "node",
                "payload": {"count": 2},
            }
        },
    }


def _members():
    return [
        {
            "uuid": f"provision.node.web#{index}",
            "instance_id": f"synthetic-web-{index}",
            "native_power_target": {
                "backend": "gce",
                "project_id": "synthetic-project",
                "zone": "europe-west3-a",
                "instance_name": f"synthetic-web-{index}",
                "bootstrap_capability": "standard",
            },
            "native_power_incarnation": {
                "instance_identity": str(100 + index),
                "disks": [{"name": f"synthetic-web-{index}-boot", "identity": str(200 + index)}],
            },
        }
        for index in range(2)
    ]


def test_power_input_retains_only_exact_generation_and_realized_targets():
    generation = uuid4()
    members = _members()
    members[0]["provider_response"] = "private material"
    payload = build_native_power_input(_plan(), members, generation, backend="gce")
    parsed = parse_native_power_input(payload, plan=_plan())
    assert parsed.resource_generation == generation
    assert [member.member_ref for member in parsed.members] == [
        "provision.node.web#0",
        "provision.node.web#1",
    ]
    assert "private material" not in repr(payload)
    assert parsed.members[0].target.project_id == "synthetic-project"
    members[0]["native_power_target"]["project_id"] = "changed"
    assert parsed.members[0].target.project_id == "synthetic-project"


@pytest.mark.parametrize(
    "fault",
    [
        "missing-member",
        "invented-member",
        "duplicate-member",
        "duplicate-target",
        "no-target",
        "unsupported-bootstrap",
        "empty-plan",
        "bad-count",
        "missing-generation",
        "backend",
        "no-incarnation",
    ],
)
def test_power_input_rejects_incomplete_or_unsupported_realizations(fault):
    plan, members, generation, backend = _plan(), _members(), uuid4(), "gce"
    if fault == "missing-member":
        members.pop()
    elif fault == "invented-member":
        members[0]["uuid"] = "provision.node.invented#0"
    elif fault == "duplicate-member":
        members[1]["uuid"] = members[0]["uuid"]
    elif fault == "duplicate-target":
        members[1]["native_power_target"] = dict(members[0]["native_power_target"])
        members[1]["instance_id"] = members[0]["instance_id"]
    elif fault == "no-target":
        del members[0]["native_power_target"]
    elif fault == "unsupported-bootstrap":
        members[0]["native_power_target"]["bootstrap_capability"] = "preconfigured-machine-host"
    elif fault == "empty-plan":
        plan["resources"] = {}
    elif fault == "bad-count":
        plan["resources"]["provision.node.web"]["payload"]["count"] = True
    elif fault == "missing-generation":
        generation = None
    elif fault == "no-incarnation":
        del members[0]["native_power_incarnation"]
    else:
        backend = "ec2"
    with pytest.raises(ValidationError):
        build_native_power_input(plan, members, generation, backend=backend)
