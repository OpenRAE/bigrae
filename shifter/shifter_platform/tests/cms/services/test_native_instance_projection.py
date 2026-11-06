"""Native READY guests use the existing safe range-instance display schema."""

from uuid import uuid4

import pytest

from cms.exceptions import CMSError
from cms.services import get_range_by_request_id
from tests.cms.services.test_principal_range_authority import principal_range

__all__ = ["principal_range"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def native(principal_range):
    actor = principal_range
    actor.member = "provision.node.synthetic_host#0"
    actor.realized.provisioned_instances = [
        {
            "uuid": actor.member,
            "name": "Synthetic workstation",
            "role": "raes-node",
            "os_type": "linux",
            "private_ip": "10.0.0.7",
            "ssh_key_secret_arn": "PRIVATE_KEY_REFERENCE_MARKER",
            "rdp_password_secret_arn": "PRIVATE_PASSWORD_REFERENCE_MARKER",
        }
    ]
    actor.realized.save(update_fields=["provisioned_instances"])
    return actor


def test_native_member_is_visible_without_a_stored_range_specification(native):
    result = get_range_by_request_id(native.credential, str(native.request.request_id))
    assert len(result.instances) == 1
    guest = result.instances[0]
    assert guest.uuid == native.member
    assert guest.role == "raes-node" and guest.os_type == "linux"
    assert guest.name == "Synthetic workstation" and guest.private_ip == "10.0.0.7"
    assert "PRIVATE_" not in result.model_dump_json()
    native.instance.refresh_from_db()
    assert native.instance.range_spec is None


def test_native_members_are_not_shown_before_native_readiness(native):
    native.realized.status = "provisioning"
    native.realized.save(update_fields=["status"])
    assert get_range_by_request_id(native.credential, str(native.request.request_id)).instances == []


def test_native_instance_projection_still_requires_matching_public_custody(native):
    native.realized.cms_range_uuid = uuid4()
    native.realized.save(update_fields=["cms_range_uuid"])
    with pytest.raises(CMSError):
        get_range_by_request_id(native.credential, str(native.request.request_id))
