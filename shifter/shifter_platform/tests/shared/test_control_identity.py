"""Google controller assertions are signature-, audience- and subject-bound."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt

from shared.control_identity import ControlAssertionError, verify_google_control_assertion

_SUBJECT = "controller@example.invalid"
_SUBJECT_ID = "123456789012345678901"


@pytest.fixture
def google_signer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    signer = crypt.RSASigner.from_string(pem, key_id="test-key")
    cert = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    response = Mock(status=200, data=json.dumps({"test-key": cert.decode()}).encode())
    return signer, Mock(return_value=response)


def _assertion(signer, **mutation):
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "aud": "control-test",
        "iss": "https://accounts.google.com",
        "iat": now,
        "exp": now + 60,
        "email": _SUBJECT,
        "email_verified": True,
        "sub": _SUBJECT_ID,
        **mutation,
    }
    return "Bearer " + jwt.encode(signer, claims).decode()


def _verify(assertion, request, *, subject_id=_SUBJECT_ID):
    verify_google_control_assertion(
        assertion,
        audience="control-test",
        expected_subject=_SUBJECT,
        expected_subject_id=subject_id,
        request=request,
    )


def test_google_assertion_with_exact_claims_is_accepted(google_signer):
    signer, request = google_signer
    _verify(_assertion(signer), request)


@pytest.mark.parametrize(
    "mutation",
    [
        {"aud": "other"},
        {"email": "other@example.invalid"},
        {"email_verified": "true"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"sub": None},
        {"sub": ""},
        {"sub": "123456789012345678902"},
    ],
)
def test_google_assertion_rejects_each_unbound_claim(google_signer, mutation):
    signer, request = google_signer
    with pytest.raises(ControlAssertionError):
        _verify(_assertion(signer, **mutation), request)


@pytest.mark.parametrize("case", ["no_bearer_prefix", "non_numeric_subject_id", "oversized"])
def test_google_assertion_rejects_bad_framing_without_echo(google_signer, case):
    signer, request = google_signer
    token = _assertion(signer)
    assertion, subject_id = {
        "no_bearer_prefix": (token[7:], _SUBJECT_ID),
        "non_numeric_subject_id": (token, "not-a-number"),
        "oversized": ("Bearer " + "x" * 16_384, _SUBJECT_ID),
    }[case]
    with pytest.raises(ControlAssertionError) as raised:
        _verify(assertion, request, subject_id=subject_id)
    assert str(raised.value) == "control.unauthorized"
    assert raised.value.__cause__ is None
