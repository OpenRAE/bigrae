"""Private management results require an explicit immutable target capability."""

import pytest

from raes_range_members import realized_management, realized_members


def output():
    return {
        "instances": [
            {
                "uuid": "provision.node.host#0",
                "name": "host",
                "os": "linux",
                "private_ip": "10.1.0.2",
                "instance_id": "synthetic-vm",
                "subnet_name": "lan",
                "participant_access_channels": [],
                "participant_access_usernames": {},
                "gcp_host_ssh_key_secret_ref": "projects/synthetic/secrets/management-only",
                "gcp_host_public_key": "ssh-ed25519 synthetic-public-key",
                "gcp_host_ssh_username": "range-management",
                "gcp_host_ssh_port": 22,
            }
        ]
    }


def test_unrequested_management_does_not_enter_participant_members():
    result = output()
    assert realized_management(result, ()) == {}
    assert "management-only" not in str(realized_members(result))


def test_only_requested_guest_management_identity_is_projected():
    result = realized_management(output(), ("provision.node.host",))
    assert set(result) == {"provision.node.host#0"}
    assert result["provision.node.host#0"]["username"] == "range-management"
    assert "management-only" in result["provision.node.host#0"]["ssh_key_secret_ref"]


@pytest.mark.parametrize("change", ["foreign-target", "missing-host-key", "invalid-port"])
def test_incomplete_or_foreign_management_refuses_readiness(change):
    value = output()
    member = value["instances"][0]
    if change == "foreign-target":
        member["uuid"] = "provision.node.other#0"
    elif change == "missing-host-key":
        member["gcp_host_public_key"] = ""
    else:
        member["gcp_host_ssh_port"] = 0
    with pytest.raises(ValueError):
        realized_management(value, ("provision.node.host",))
