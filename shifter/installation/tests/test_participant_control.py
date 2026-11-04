"""Deployment intent binds a fixed installation, with no code or endpoint selectors."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from shared.participant_control_installation import NativeControlInstallation

from installation.participant_control import ParticipantControlSettings, project_participant_control

_OWNER = "registry.example.test/platform@sha256:" + "1" * 64
_PROVISIONER = "registry.example.test/provisioner@sha256:" + "2" * 64
_CA = (Path(__file__).parent / "fixtures/participant-control-ca.pem").read_text()


def _policy():
    return {"enabled": True, "tls_secret_name": "participant-control-tls-v1", "trust_ca_pem": _CA}


def project(raw):
    return project_participant_control(
        raw, namespace="shifter-platform", owner_image=_OWNER, provisioner_image=_PROVISIONER
    )


def test_disabled_projection_explicitly_clears_old_coordinates_and_cannot_start_an_owner():
    values, environment = project(None)
    assert values == {"enabled": False}
    assert environment == {
        "PARTICIPANT_CONTROL_ENABLED": "false",
        "PARTICIPANT_CONTROL_OWNER_PROCESS": "false",
        "PARTICIPANT_CONTROL_CONFIGURATION": "",
    }


def test_enabled_projection_derives_images_namespace_and_runtime_limits():
    policy = {**_policy(), "max_contexts": 4, "idle_seconds": 60, "budgets": {"commit_ms": 1200}}
    values, environment = project(policy)
    installed = NativeControlInstallation.model_validate_json(values["configuration"])
    assert installed.namespace == "shifter-platform"
    assert installed.owner_image == _OWNER
    assert installed.provisioner_image == _PROVISIONER
    assert installed.max_contexts == 4
    assert installed.idle_seconds == 60
    assert installed.budgets.commit_ms == 1200
    assert installed.trust_ca_pem == _CA
    assert values["tlsSecretName"] == policy["tls_secret_name"]
    assert environment["PARTICIPANT_CONTROL_CONFIGURATION"] == values["configuration"]
    assert environment["PARTICIPANT_CONTROL_ENABLED"] == "true"
    assert environment["PARTICIPANT_CONTROL_OWNER_PROCESS"] == "false"
    assert json.loads(values["configuration"])["protocol"] == "shifter-native-power-installation/v1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "arbitrary.module:main"),
        ("origin", "https://unapproved.invalid"),
        ("store_root", "/unapproved/shared"),
        ("owner_image", _OWNER),
        ("namespace", "foreign"),
        ("max_contexts", 0),
        ("idle_seconds", 86400),
        ("budgets", {"execution_ms": 0}),
        ("storage_gib", 0),
        ("enabled", "true"),
        ("tls_secret_name", ""),
        ("trust_ca_pem", ""),
    ],
)
def test_unknown_selectors_or_incomplete_unbounded_intent_are_rejected(field, value):
    with pytest.raises(ValidationError):
        project({**_policy(), field: value})


@pytest.mark.parametrize("raw", [False, [], "", {"tls_secret_name": "stale-transport"}, {"trust_ca_pem": _CA}])
def test_malformed_or_disabled_active_intent_is_not_silently_defaulted(raw):
    with pytest.raises(ValidationError):
        project(raw)


def test_public_trust_parser_does_not_echo_pasted_private_material():
    material = "synthetic-private-material"
    with pytest.raises(ValidationError) as failure:
        ParticipantControlSettings.model_validate({**_policy(), "trust_ca_pem": material})
    assert material not in str(failure.value)


@pytest.mark.parametrize("image", ["registry.example.test/provisioner:latest", "sha256:" + "2" * 64, ""])
def test_enabled_installation_requires_the_actual_immutable_release_images(image):
    with pytest.raises(ValidationError):
        project_participant_control(
            _policy(), namespace="shifter-platform", owner_image=_OWNER, provisioner_image=image
        )
