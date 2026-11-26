"""CRL refresh queues one job per needed publication and no more."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from tests.engine.services.test_principal_vpn import principal_range, vpn_range

pytestmark = [pytest.mark.django_db]
__all__ = ["principal_range", "vpn_range"]


def _finish(operation_id, request_id, operation):
    """Record accepted native terminal evidence for one PKI operation."""
    from engine.models import OperationResultInbox
    from shared.operation_envelope import build_operation_envelope, canonical_payload_digest

    payload = {"operation_id": str(operation_id)}
    envelope = build_operation_envelope(
        operation_id=operation_id, request_id=request_id, resource="vpn-profile", operation=operation, payload=payload
    )
    OperationResultInbox.objects.create(
        operation_id=operation_id,
        request_id=request_id,
        resource="vpn-profile",
        operation=operation,
        contract_version=envelope["contract_version"],
        result_kind="TERMINAL_SUCCESS",
        result_step="vpn_pki_ready",
        result_identity=str(uuid4()),
        payload_digest=canonical_payload_digest(payload),
        envelope=envelope,
        disposition="APPLIED",
    )


def _live_profiles(fixture):
    """Return two issued profiles, so a refresh can rotate to a second candidate."""
    from engine.models import VpnAccessProfile
    from engine.services._vpn.profiles import request_vpn_profile

    first = request_vpn_profile(fixture.credential, fixture.request.request_id)
    first.state, first.certificate_serial = "ready", "1234"
    first.save(update_fields=["state", "certificate_serial", "updated_at"])
    _finish(first.provisioner_operation_id, first.generation, "issue")
    skipped = {"id", "resource_generation", "certificate_serial", "created_at", "updated_at"}
    fields = {
        field.attname: getattr(first, field.attname)
        for field in VpnAccessProfile._meta.concrete_fields
        if field.attname not in skipped
    }
    second = VpnAccessProfile.objects.create(**fields, resource_generation=uuid4(), certificate_serial="5678")
    return first, second


def _publish(revision, expires_in):
    """Apply the CRL publication that an accepted PKI receipt commits."""
    from engine.models import VpnCrlState

    state = VpnCrlState.objects.get(pk=1)
    state.published_revision, state.pem = revision, f"synthetic-crl-{revision}"
    state.expires_at = timezone.now() + expires_in
    state.save()


def _requested_revision():
    from engine.models import VpnCrlState

    return VpnCrlState.objects.get(pk=1).requested_revision


def _refresh_inputs():
    from engine.models import OperationInput

    return [
        row.envelope["payload"]
        for row in OperationInput.objects.filter(resource="vpn-profile", operation="refresh-crl").order_by("created_at")
    ]


def test_pending_revision_publishes_once_without_a_new_revision(vpn_range):
    from engine.models import VpnAccessProfile
    from engine.services._vpn.profiles import _refresh_vpn_crl

    _live_profiles(vpn_range)
    pending = _requested_revision()
    _refresh_vpn_crl()
    _refresh_vpn_crl()
    inputs = _refresh_inputs()
    assert [value["crl_revision"] for value in inputs] == [pending]
    assert _requested_revision() == pending
    refreshed = VpnAccessProfile.objects.get(provisioner_operation="refresh-crl")
    _finish(refreshed.provisioner_operation_id, refreshed.generation, "refresh-crl")
    _publish(pending, timedelta(days=7))
    _refresh_vpn_crl()
    assert len(_refresh_inputs()) == 1
    assert _requested_revision() == pending


def test_revocation_adds_one_revision_and_one_refresh(vpn_range):
    from engine.services._vpn.profile_operations import queue_vpn_operation
    from engine.services._vpn.profiles import _refresh_vpn_crl

    _first, second = _live_profiles(vpn_range)
    _publish(_requested_revision(), timedelta(days=7))
    _refresh_vpn_crl()
    assert _refresh_inputs() == []
    published = _requested_revision()
    second.state, second.revoked_at = "revoked", timezone.now()
    second.save(update_fields=["state", "revoked_at", "updated_at"])
    queue_vpn_operation(second, "revoke")
    assert _requested_revision() == published + 1
    _refresh_vpn_crl()
    _refresh_vpn_crl()
    inputs = _refresh_inputs()
    assert [value["crl_revision"] for value in inputs] == [published + 1]
    assert [row["serial"] for row in inputs[0]["revocations"]] == ["5678"]
    assert _requested_revision() == published + 1


def test_expiring_published_list_renews_with_one_new_revision(vpn_range):
    from engine.services._vpn.profiles import _refresh_vpn_crl

    _live_profiles(vpn_range)
    published = _requested_revision()
    _publish(published, timedelta(hours=1))
    _refresh_vpn_crl()
    _refresh_vpn_crl()
    assert [value["crl_revision"] for value in _refresh_inputs()] == [published + 1]
    assert _requested_revision() == published + 1
