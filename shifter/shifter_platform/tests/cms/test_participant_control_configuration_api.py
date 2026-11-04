"""Native organization administration cannot install code or borrow controller authority."""

from dataclasses import asdict

import pytest
from rest_framework.test import APIClient

from tests.cms.test_participant_control_configuration import controlled_pack, controlled_source, tenant
from tests.shared.raes.test_native_power_package import selection

__all__ = ["controlled_pack", "controlled_source", "tenant"]
pytestmark = pytest.mark.django_db


def endpoint(item):
    return f"/api/v1/participant-control/organizations/{item[1].uuid}/sources/{item[2].scenario_id}/"


def body(item):
    return {"expected_package_digest": item[2].package_digest, "selection": asdict(selection())}


def test_source_configuration_is_authenticated_scoped_and_never_starts_a_runtime(controlled_pack):
    from cms.models import ParticipantControlBinding, ParticipantControlConfiguration
    from engine.models import ParticipantPowerReservation

    item = controlled_pack
    client = APIClient()
    client.force_login(item[0])
    initial = client.get(endpoint(item))
    assert initial.status_code == 200, initial.json()
    assert "no-store" in initial["Cache-Control"]
    assert initial.json() == {"configuration": None, "requires_refresh": False}
    response = client.post(endpoint(item), body(item), format="json")
    assert response.status_code == 201, response.json()
    current = client.get(endpoint(item))
    assert current.json() == {"configuration": response.json(), "requires_refresh": False}
    assert response.json()["selection"] == asdict(selection())
    assert ParticipantControlConfiguration.objects.count() == 1
    assert not ParticipantControlBinding.objects.exists()
    assert not ParticipantPowerReservation.objects.exists()


def test_stale_source_digest_reports_refresh_and_cannot_be_silently_reconfigured(controlled_pack):
    from cms.models import RaesPackageSource

    client = APIClient()
    client.force_login(controlled_pack[0])
    original = body(controlled_pack)
    assert client.post(endpoint(controlled_pack), original, format="json").status_code == 201
    RaesPackageSource.objects.filter(pk=controlled_pack[2].pk).update(package_digest="sha256:" + "f" * 64)
    status = client.get(endpoint(controlled_pack))
    assert status.status_code == 200 and status.json()["requires_refresh"]
    assert client.post(endpoint(controlled_pack), original, format="json").status_code == 409


@pytest.mark.parametrize("condition", ["anonymous", "denied", "csrf", "invalid-bearer"])
def test_source_admin_ingress_does_not_fall_back_to_session_or_privileged_identity(controlled_pack, condition):
    from cms.models import ParticipantControlConfiguration

    client = APIClient(enforce_csrf_checks=condition == "csrf")
    if condition != "anonymous":
        client.force_login(controlled_pack[0])
    if condition == "denied":
        controlled_pack[0].policy_principals.clear()
    if condition == "invalid-bearer":
        client.credentials(HTTP_AUTHORIZATION="Bearer shf_synthetic_invalid")
    response = client.post(endpoint(controlled_pack), body(controlled_pack), format="json")
    assert response.status_code in {401, 403}
    assert not ParticipantControlConfiguration.objects.exists()


@pytest.mark.parametrize("field", ["provider", "url", "store_root", "credential", "implementation"])
@pytest.mark.parametrize("nested", [False, True])
def test_source_admin_rejects_executable_transport_and_authority_selectors(controlled_pack, field, nested):
    from cms.models import ParticipantControlConfiguration

    client = APIClient()
    client.force_login(controlled_pack[0])
    data = body(controlled_pack)
    (data["selection"] if nested else data)[field] = "synthetic-private-credential-value"
    response = client.post(endpoint(controlled_pack), data, format="json")
    assert response.status_code == 400
    assert "synthetic-private-credential-value" not in str(response.json())
    assert not ParticipantControlConfiguration.objects.exists()


def test_source_admin_masks_private_configuration_causes(controlled_pack, monkeypatch):
    from unittest.mock import Mock

    client = APIClient()
    client.force_login(controlled_pack[0])
    monkeypatch.setattr(
        "cms.api.participant_control_configuration.configure_native_participant_control",
        Mock(side_effect=RuntimeError("synthetic-private-provider-cause")),
    )
    response = client.post(endpoint(controlled_pack), body(controlled_pack), format="json")
    assert response.status_code == 503
    assert "synthetic-private-provider-cause" not in str(response.json())
