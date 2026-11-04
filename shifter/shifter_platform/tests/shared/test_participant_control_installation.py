"""Installation selects fixed pinned application images and finite native limits."""

from datetime import UTC, datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding


@pytest.fixture
def installation_values():
    return synthetic_installation_values()


def synthetic_installation_values():
    """Create public synthetic trust and deployment identities, without external files."""
    key = ed25519.Ed25519PrivateKey.generate()
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Synthetic control CA")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2100, 1, 1, tzinfo=UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)
    )
    return {
        "protocol": "shifter-native-power-installation/v1",
        "namespace": "synthetic-platform",
        "owner_image": "registry.example.test/platform@sha256:" + "1" * 64,
        "provisioner_image": "registry.example.test/provisioner@sha256:" + "2" * 64,
        "trust_ca_pem": certificate.public_bytes(Encoding.PEM).decode(),
    }


def test_native_installation_pins_fixed_origin_storage_images_and_limits(installation_values):
    from shared.participant_control_installation import NativeControlInstallation

    installed = NativeControlInstallation.model_validate(installation_values)
    assert installed.control_origin == "https://participant-control.synthetic-platform.svc:8445"
    assert str(installed.store_root) == "/var/lib/shifter/participant-control"
    assert installed.digest.startswith("sha256:")
    assert installed.max_contexts == 8
    assert installed.budgets.admission_ms > 0
    changed = NativeControlInstallation.model_validate({**installation_values, "max_contexts": 9})
    assert changed.digest != installed.digest
    assert changed.policy_digest == installed.policy_digest


def test_policy_pin_survives_transport_rotation_but_retains_original_control_budgets(installation_values):
    from shared.participant_control_installation import NativeControlInstallation

    original = NativeControlInstallation.model_validate(installation_values)
    transport = NativeControlInstallation.model_validate(
        {
            **installation_values,
            "namespace": "replacement-platform",
            "owner_image": "example.test/platform@sha256:" + "a" * 64,
            "provisioner_image": "example.test/provisioner@sha256:" + "b" * 64,
            "trust_ca_pem": synthetic_installation_values()["trust_ca_pem"],
        }
    )
    assert original.digest != transport.digest
    assert original.policy_digest == transport.policy_digest
    altered_policy = NativeControlInstallation.model_validate(
        {
            **installation_values,
            "budgets": {"admission_ms": 11_000},
        }
    )
    assert original.policy_digest != altered_policy.policy_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_image", "registry.example.test/platform:latest"),
        ("provisioner_image", "registry.example.test/provisioner:latest"),
        ("namespace", "foreign/namespace"),
        ("max_contexts", 0),
        ("max_contexts", 10000),
        ("idle_seconds", 0),
        ("budgets", {"admission_ms": 0}),
        ("budgets", {"execution_ms": 9999999}),
        ("budgets", {"admission_ms": True}),
        ("provider", "synthetic.arbitrary.code"),
        ("control_origin", "http://untrusted.example.test"),
        ("store_root", "/caller-selected"),
        ("trust_ca_pem", "synthetic-invalid-cert"),
    ],
)
def test_native_installation_rejects_unpinned_unbounded_and_caller_selected_values(installation_values, field, value):
    from pydantic import ValidationError

    from shared.participant_control_installation import NativeControlInstallation

    with pytest.raises(ValidationError):
        NativeControlInstallation.model_validate({**installation_values, field: value})


def test_public_trust_bundle_cannot_smuggle_private_material(installation_values):
    from pydantic import ValidationError

    from shared.participant_control_installation import NativeControlInstallation

    changed = {
        **installation_values,
        "trust_ca_pem": installation_values["trust_ca_pem"] + "\n-----BEGIN PRIVATE KEY-----\nsynthetic",
    }
    with pytest.raises(ValidationError):
        NativeControlInstallation.model_validate(changed)


@pytest.mark.parametrize(
    "enabled,owner,raw",
    [
        (True, False, ""),
        (False, True, ""),
        (False, False, '{"duplicate":1,"duplicate":2}'),
        (False, False, "synthetic-private-invalid-input"),
    ],
)
def test_runtime_settings_reject_missing_ambiguous_or_invalid_installation(enabled, owner, raw):
    from django.core.exceptions import ImproperlyConfigured

    from config._participant_control_settings import load_native_control_installation

    with pytest.raises(ImproperlyConfigured) as error:
        load_native_control_installation(raw, enabled=enabled, owner_process=owner)
    assert "synthetic-private-invalid-input" not in str(error.value)


def test_runtime_settings_admit_exact_native_installation(installation_values):
    import json

    from config._participant_control_settings import load_native_control_installation

    installed = load_native_control_installation(json.dumps(installation_values), enabled=True, owner_process=True)
    assert installed.owner_image == installation_values["owner_image"]
    assert load_native_control_installation("", enabled=False, owner_process=False) is None
