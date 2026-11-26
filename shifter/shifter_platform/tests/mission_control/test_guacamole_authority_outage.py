"""An authorization evaluator outage is not a revocation of a live remote session."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection

from cms.exceptions import CMSError
from shared.authorization import AuthorizationDecision, AuthorizationUnavailable, DecisionKind
from tests.cms._device_fixtures import _ngfw_catalog
from tests.cms.services.test_principal_content import content_actor
from tests.cms.services.test_principal_devices import device_administrator, provisioned_device
from tests.cms.services.test_principal_range_authority import principal_range
from tests.mission_control.test_guacamole_control import gateway_claims, post
from tests.mission_control.test_principal_guacamole import Gateway

pytestmark = [pytest.mark.django_db]
__all__ = [
    "_ngfw_catalog",
    "content_actor",
    "device_administrator",
    "gateway_claims",
    "principal_range",
    "provisioned_device",
]


# The inline bootstrap worker closes old connections, so these tests need real
# transactions. SQLite cannot flush the immutable provider binding afterwards.
_INLINE_BOOTSTRAP_DB = pytest.mark.django_db(transaction=True)
_POSTGRES_ONLY = (
    pytest.mark.postgres,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Transactional flush requires PostgreSQL"),
)


def _inline_bootstrap(test):
    """Mark one test that launches a real inline bootstrap session."""
    for mark in (*_POSTGRES_ONLY, _INLINE_BOOTSTRAP_DB):
        test = mark(test)
    return test


def _bind_decision(monkeypatch, kind):
    """Bind one provider decision for every check after this point."""
    from shared.authorization import port

    reason = {
        DecisionKind.ALLOWED: "policy_allowed",
        DecisionKind.DENIED: "policy_denied",
        DecisionKind.EVALUATOR_ERROR: "evaluator_unavailable",
    }[kind]

    def check(_request):
        return AuthorizationDecision(kind, reason)

    provider = SimpleNamespace(check=check, batch_check=lambda requests: tuple(check(item) for item in requests))
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)


def _bind_failing_provider(monkeypatch):
    """Bind a provider whose check raises, as an evaluator timeout does."""
    from shared.authorization import port

    def check(_request):
        raise TimeoutError("synthetic evaluator timeout")

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))


@pytest.fixture
def device_session(provisioned_device, settings, monkeypatch):
    """Create one admitted native device session through the real launch path."""
    from mission_control.guacamole_session import launch_guacamole_session
    from mission_control.models import GuacamoleBootstrapRequest

    actor = provisioned_device
    actor.native.state = {"management_ip": "192.0.2.10", "ssh_key_secret_id": "synthetic-device-key"}
    actor.native.save(update_fields=["state"])
    monkeypatch.setattr("engine.services._terminal.get_ssh_key", lambda reference: "SYNTHETIC_TEST_KEY")
    settings.GUACAMOLE_BOOTSTRAP_INLINE = True
    gateway = Gateway()
    result = launch_guacamole_session(
        user=actor.credential, protocol="ngfw_ssh", target_id=str(actor.app.pk), guacamole_client=gateway
    )
    row = GuacamoleBootstrapRequest.objects.get(pk=result.bootstrap_id)
    assert row.status == "succeeded"
    return SimpleNamespace(actor=actor, gateway=gateway, row=row)


@_inline_bootstrap
def test_renewal_during_evaluator_outage_answers_unavailable(device_session, gateway_claims, monkeypatch):
    from mission_control.guacamole_authority import renew_gateway_authority

    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(AuthorizationUnavailable):
        renew_gateway_authority(str(device_session.row.pk))
    response = post({"bootstrap": str(device_session.row.pk)})
    assert response.status_code == 503
    assert response.json() == {"error": "gateway.authority_unavailable"}


@_inline_bootstrap
def test_renewal_after_policy_denial_still_answers_closed(device_session, gateway_claims, monkeypatch):
    _bind_decision(monkeypatch, DecisionKind.DENIED)
    response = post({"bootstrap": str(device_session.row.pk)})
    assert response.status_code == 200
    assert response.json() == {"allowed": False}


@_inline_bootstrap
def test_revalidation_keeps_native_session_during_evaluator_outage(device_session, monkeypatch):
    from mission_control.guacamole_authority import renew_gateway_authority, revalidate_guacamole_sessions

    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    assert revalidate_guacamole_sessions(client=device_session.gateway) == 0
    device_session.row.refresh_from_db()
    assert device_session.row.native_terminated_at is None
    assert device_session.row.native_session_token
    assert device_session.gateway.closed == []
    _bind_decision(monkeypatch, DecisionKind.ALLOWED)
    assert renew_gateway_authority(str(device_session.row.pk))


def test_session_creation_refuses_during_evaluator_outage(provisioned_device, settings, monkeypatch):
    from mission_control.guacamole_bootstrap import BootstrapFailure
    from mission_control.guacamole_session import launch_guacamole_session
    from mission_control.models import GuacamoleBootstrapRequest

    settings.GUACAMOLE_BOOTSTRAP_INLINE = True
    gateway = Gateway()
    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(BootstrapFailure) as refused:
        launch_guacamole_session(
            user=provisioned_device.credential,
            protocol="ngfw_ssh",
            target_id=str(provisioned_device.app.pk),
            guacamole_client=gateway,
        )
    assert refused.value.status_code == 403
    assert not GuacamoleBootstrapRequest.objects.exists()
    assert not hasattr(gateway, "last_identity")


@_inline_bootstrap
def test_existing_authorize_bootstrap_callers_still_deny_during_outage(device_session, monkeypatch):
    from mission_control.guacamole_authority import authorize_bootstrap

    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    assert authorize_bootstrap(device_session.row) is False


@pytest.mark.parametrize("bind", ["evaluator_error", "provider_raises"])
def test_native_range_action_reports_evaluator_outage(principal_range, monkeypatch, bind):
    from engine.services._range_authority import require_native_range_action

    if bind == "evaluator_error":
        _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    else:
        _bind_failing_provider(monkeypatch)
    with pytest.raises(AuthorizationUnavailable):
        require_native_range_action(principal_range.credential, principal_range.request.request_id, "range.access")


def test_native_range_action_keeps_bounded_denials(principal_range, monkeypatch):
    from engine.services._range_authority import require_native_range_action

    _bind_decision(monkeypatch, DecisionKind.DENIED)
    with pytest.raises(PermissionError) as denied:
        require_native_range_action(principal_range.credential, principal_range.request.request_id, "range.access")
    assert not isinstance(denied.value, AuthorizationUnavailable)
    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(PermissionError) as missing:
        require_native_range_action(principal_range.credential, uuid4(), "range.access")
    assert not isinstance(missing.value, AuthorizationUnavailable)


@pytest.mark.postgres
@pytest.mark.skipif(
    not connection.features.supports_json_field_contains,
    reason="Native range guest selection requires PostgreSQL JSON containment",
)
def test_instance_range_carries_only_evaluator_outage(principal_range, monkeypatch):
    from engine.services._range_authority import authorized_instance_range

    target = "provision.node.client#0"
    principal_range.realized.provisioned_instances = [{"uuid": target}]
    principal_range.realized.save(update_fields=["provisioned_instances"])
    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(AuthorizationUnavailable):
        authorized_instance_range(principal_range.credential, target, range_uuid=principal_range.instance.uuid)
    _bind_decision(monkeypatch, DecisionKind.DENIED)
    with pytest.raises(PermissionError) as denied:
        authorized_instance_range(principal_range.credential, target, range_uuid=principal_range.instance.uuid)
    assert not isinstance(denied.value, AuthorizationUnavailable)


def test_native_device_access_carries_only_evaluator_outage(provisioned_device, monkeypatch):
    from engine.services import admit_native_device_access

    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(AuthorizationUnavailable):
        admit_native_device_access(provisioned_device.credential, str(provisioned_device.app.pk))
    _bind_decision(monkeypatch, DecisionKind.DENIED)
    with pytest.raises(PermissionError) as denied:
        admit_native_device_access(provisioned_device.credential, str(provisioned_device.app.pk))
    assert not isinstance(denied.value, AuthorizationUnavailable)


def test_device_remote_authority_marks_only_evaluator_outage(provisioned_device, monkeypatch):
    from cms.services import admit_device_remote_authority

    _bind_decision(monkeypatch, DecisionKind.EVALUATOR_ERROR)
    with pytest.raises(CMSError) as outage:
        admit_device_remote_authority(provisioned_device.credential, str(provisioned_device.app.pk))
    assert outage.value.details == {"code": "authority-unavailable"}
    _bind_decision(monkeypatch, DecisionKind.DENIED)
    with pytest.raises(CMSError) as denied:
        admit_device_remote_authority(provisioned_device.credential, str(provisioned_device.app.pk))
    assert denied.value.details == {}


def test_device_remote_authority_marks_native_evaluator_outage(provisioned_device, monkeypatch):
    from cms.services import admit_device_remote_authority

    def unavailable(credential, identifier):
        raise AuthorizationUnavailable("Device access unavailable")

    monkeypatch.setattr("engine.services.admit_native_device_access", unavailable)
    with pytest.raises(CMSError) as outage:
        admit_device_remote_authority(provisioned_device.credential, str(provisioned_device.app.pk))
    assert outage.value.details == {"code": "authority-unavailable"}
