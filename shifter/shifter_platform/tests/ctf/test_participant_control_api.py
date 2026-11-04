"""Authenticated management requests traverse the actual persistent native owner."""

from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient

from tests.cms.conftest import make_pack
from tests.cms.test_participant_control_binding import controlled_pack, controlled_source, product_range, tenant

__all__ = ["controlled_pack", "controlled_source", "make_pack", "product_range", "tenant"]
pytestmark = pytest.mark.django_db(transaction=True)
_PREFIX = "/api/v1/participant-control/ctf"


@pytest.fixture
def installed_worker(product_range, settings, tmp_path):
    from cms.participant_control_runtime import (
        close_participant_control_registry,
        install_participant_control_registry,
    )
    from cms.services._participant_control_registry import NativeParticipantControlRegistry

    settings.PARTICIPANT_CONTROL_ENABLED = True
    settings.PARTICIPANT_CONTROL_OWNER_PROCESS = True
    registry = NativeParticipantControlRegistry(settings.PARTICIPANT_CONTROL_INSTALLATION, store_root=tmp_path)
    install_participant_control_registry(registry)
    try:
        yield product_range
    finally:
        close_participant_control_registry()


def bind(client, item):
    return client.post(
        f"{_PREFIX}/participants/{item.subject.pk}/binding/", {"configuration_id": str(item.config.id)}, format="json"
    )


def test_binding_discovery_returns_only_opaque_current_choices_without_private_decryption(installed_worker, settings):
    from cryptography.fernet import Fernet

    item = installed_worker
    client = APIClient()
    client.force_login(item.case.actor)
    url = f"{_PREFIX}/participants/{item.subject.pk}/binding/"
    initial = client.get(url)
    assert initial.status_code == 200, initial.json()
    assert "no-store" in initial["Cache-Control"]
    assert initial.json() == {"configuration_id": str(item.config.id), "binding_id": None, "requires_refresh": False}
    created = bind(client, item)
    assert created.status_code == 201, created.json()
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    recovered = client.get(url)
    assert recovered.status_code == 200, recovered.json()
    assert recovered.json() == {
        "configuration_id": str(item.config.id),
        "binding_id": created.json()["binding_id"],
        "requires_refresh": False,
    }


def test_authenticated_controller_path_records_review_and_releases_exact_work(installed_worker):
    from engine.models import ParticipantPowerReservation

    item = installed_worker
    client = APIClient()
    client.force_login(item.case.actor)
    response = bind(client, item)
    assert response.status_code == 201, response.json()
    assert "no-store" in response["Cache-Control"]
    view = response.json()
    binding_id, proposal_id, action_id = view["binding_id"], uuid4(), uuid4()
    for kind in ("proposal", "approval", "action"):
        response = client.post(
            f"{_PREFIX}/bindings/{binding_id}/commands/",
            {
                "request_id": str(proposal_id if kind == "proposal" else action_id if kind == "action" else uuid4()),
                "kind": kind,
                "verb": "pause",
                "proposal_id": str(proposal_id),
                "action_id": str(action_id),
                "expected_cut_digest": view["control_cut_digest"],
            },
            format="json",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["state"] == "succeeded"
        current = client.get(f"{_PREFIX}/bindings/{binding_id}/")
        assert current.status_code == 200, current.json()
        view = current.json()
    reservation = ParticipantPowerReservation.objects.select_related("launch_intent").get(action_id=action_id)
    assert reservation.released_at is not None
    assert reservation.launch_intent.status == "PENDING"
    assert reservation.portable_operation_uuid == UUID(response.json()["operation_id"])
    assert view["range_status"] == "pausing"
    assert len(view["commands"]) == 3
    assert all("credential" not in str(command) and "request_json" not in str(command) for command in view["commands"])
    from cms.participant_control_runtime import participant_control_registry
    from tests.shared.raes.test_native_power_conformance import assert_native_control_records_conform

    with participant_control_registry().lease(item.case.credential, UUID(binding_id)) as owner:
        assert_native_control_records_conform(owner.session)


@pytest.mark.parametrize("condition", ["anonymous", "denied", "csrf", "invalid-bearer"])
def test_authentication_scope_and_csrf_cannot_be_bypassed(installed_worker, condition):
    from cms.models import ParticipantControlBinding, ParticipantControlCommand

    item = installed_worker
    client = APIClient(enforce_csrf_checks=condition == "csrf")
    if condition != "anonymous":
        client.force_login(item.case.actor)
    if condition == "denied":
        item.case.actor.policy_principals.clear()
    if condition == "invalid-bearer":
        client.credentials(HTTP_AUTHORIZATION="Bearer synthetic-invalid-token")
    response = bind(client, item)
    assert response.status_code in {401, 403}, response.content
    assert not ParticipantControlBinding.objects.exists()
    assert not ParticipantControlCommand.objects.exists()


def test_control_api_rejects_executable_selectors_before_owner_or_effect(installed_worker):
    from cms.models import ParticipantControlBinding

    client = APIClient()
    client.force_login(installed_worker.case.actor)
    response = client.post(
        f"{_PREFIX}/participants/{installed_worker.subject.pk}/binding/",
        {
            "configuration_id": str(installed_worker.config.id),
            "provider": "synthetic.arbitrary.module",
        },
        format="json",
    )
    assert response.status_code == 400
    assert not ParticipantControlBinding.objects.exists()


def test_portal_process_cannot_create_an_ephemeral_controller(installed_worker, settings):
    from cms.models import ParticipantControlBinding

    client = APIClient()
    client.force_login(installed_worker.case.actor)
    settings.PARTICIPANT_CONTROL_OWNER_PROCESS = False
    try:
        response = bind(client, installed_worker)
    finally:
        settings.PARTICIPANT_CONTROL_OWNER_PROCESS = True
    assert response.status_code == 503
    assert not ParticipantControlBinding.objects.exists()


def test_retry_recovers_original_request_without_new_bytes_or_control_cut(installed_worker):
    from cms.models import ParticipantControlCommand

    client = APIClient()
    client.force_login(installed_worker.case.actor)
    view = bind(client, installed_worker).json()
    proposal, action = str(uuid4()), str(uuid4())
    command_path = f"{_PREFIX}/bindings/{view['binding_id']}/commands/"
    original = client.post(
        command_path,
        {
            "request_id": proposal,
            "kind": "proposal",
            "verb": "pause",
            "proposal_id": proposal,
            "action_id": action,
            "expected_cut_digest": view["control_cut_digest"],
        },
        format="json",
    )
    assert original.status_code == 200, original.json()
    saved = ParticipantControlCommand.objects.get(pk=proposal)
    original_bytes = bytes(saved.request_json)
    retry = f"{command_path}{proposal}/retry/"
    assert client.post(retry, {"expected_cut_digest": "sha256:" + "f" * 64}, format="json").status_code == 400
    repeated = client.post(retry, {}, format="json")
    assert repeated.status_code == 200, repeated.json()
    assert repeated.json() == original.json()
    assert bytes(ParticipantControlCommand.objects.get(pk=proposal).request_json) == original_bytes
    assert ParticipantControlCommand.objects.count() == 1
    installed_worker.case.actor.policy_principals.clear()
    assert client.post(retry, {}, format="json").status_code == 403
