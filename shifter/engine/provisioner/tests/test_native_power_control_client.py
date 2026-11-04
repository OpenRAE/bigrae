"""Native grant HTTP uses closed TLS, fixed routes, bounded bodies and Job proof."""

import json
import ssl
from io import BytesIO
from unittest.mock import Mock
from urllib.request import HTTPSHandler, ProxyHandler
from uuid import uuid4

import pytest
from shared.native_power_protocol import native_power_grant_payload
from shared.participant_control_installation import NativeControlInstallation

from tests.conftest import build_vpn_issuer_payload
from tests.test_native_power_invocation import native_call, permission

__all__ = ["native_call"]


class _Response(BytesIO):
    status = 200


@pytest.fixture
def transport(native_call, tmp_path, monkeypatch):
    import native_power_control_client as module

    ca = json.loads(build_vpn_issuer_payload())["ca"]
    installed = NativeControlInstallation.model_validate(
        {
            "protocol": "shifter-native-power-installation/v1",
            "namespace": "synthetic-platform",
            "owner_image": "registry.example.test/platform@sha256:" + "1" * 64,
            "provisioner_image": "registry.example.test/provisioner@sha256:" + "2" * 64,
            "trust_ca_pem": ca,
        }
    )
    token = tmp_path / "native-workload-token"
    token.write_text("fixture.bound.token")
    monkeypatch.setattr(module, "_TOKEN_PATH", token)
    wire = Mock()
    handlers = []

    def opener(*configured):
        handlers.extend(configured)
        return wire

    monkeypatch.setattr(module, "build_opener", opener)
    client = module.NativePowerControlClient(installed)
    wire.open.return_value = _Response(json.dumps(native_power_grant_payload(permission(native_call))).encode())
    return client, wire, handlers


def test_acquire_sends_only_fixed_private_request_with_native_job_token(transport, native_call):
    client, wire, handlers = transport
    grant = client.acquire(native_call.operation_id, native_call.member.member_ref, native_call.attempt_id)
    assert grant == permission(native_call)
    request = wire.open.call_args.args[0]
    assert (
        request.full_url
        == "https://participant-control.synthetic-platform.svc:8445/internal/participant-control/invocations/begin/"
    )
    assert json.loads(request.data) == {
        "operation_id": str(native_call.operation_id),
        "member_ref": native_call.member.member_ref,
        "attempt_id": str(native_call.attempt_id),
    }
    assert request.headers["Authorization"] == "Bearer fixture.bound.token"
    assert wire.open.call_args.kwargs["timeout"] == 5
    assert next(handler for handler in handlers if isinstance(handler, ProxyHandler)).proxies == {}
    context = next(handler for handler in handlers if isinstance(handler, HTTPSHandler))._context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize("fault", ["unknown", "malformed", "oversized", "private-error"])
def test_unusable_grant_never_retries_or_exposes_private_diagnostics(transport, native_call, fault):
    from native_power_control_client import NativePowerTransportError

    client, wire, _ = transport
    if fault == "private-error":
        wire.open.side_effect = RuntimeError("synthetic-private-provider-detail")
    else:
        payload = native_power_grant_payload(permission(native_call))
        if fault == "unknown":
            payload["provider"] = "synthetic.arbitrary.module"
        raw = b"{" if fault == "malformed" else b"x" * 32769 if fault == "oversized" else json.dumps(payload).encode()
        wire.open.return_value = _Response(raw)
    with pytest.raises(NativePowerTransportError) as error:
        client.acquire(native_call.operation_id, native_call.member.member_ref, native_call.attempt_id)
    assert wire.open.call_count == 1
    assert "synthetic-private-provider-detail" not in str(error.value)
    assert error.value.__cause__ is None


def test_completion_is_a_separate_idempotent_metadata_request(transport):
    client, wire, _ = transport
    response = _Response(b"")
    response.status = 204
    wire.open.return_value = response
    invocation = uuid4()
    client.complete(invocation, invocation)
    request = wire.open.call_args.args[0]
    assert request.full_url.endswith("/internal/participant-control/invocations/finish/")
    assert json.loads(request.data) == {"invocation_id": str(invocation), "attempt_id": str(invocation)}
