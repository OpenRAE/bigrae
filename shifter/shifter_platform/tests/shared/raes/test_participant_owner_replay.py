"""Admission replays only the configurations and selections the backend owner validated."""

from types import SimpleNamespace

import pytest
from raes_contracts.canonical import canonical_contract_digest, canonical_json_digest
from raes_contracts.contracts import ParticipantConfigurationModel

from shared.raes.participant_owner_replay import ReplayedConfigurationValidator


def configuration(version: str) -> ParticipantConfigurationModel:
    return ParticipantConfigurationModel.model_validate(
        {
            "implementation_identity": {"name": "lilrae-opencode", "version": version},
            "manifest_version": "participant-implementation-manifest/v1",
            "owner": {
                "contract_id": "participant-implementation-manifest/v1",
                "contract_version": "1",
                "validator_id": "lilrae-opencode-request",
                "validator_version": "1",
            },
            "values": [
                {
                    "target_id": "model",
                    "value_type": "string",
                    "origin": "override",
                    "value": {"kind": "literal", "value": "google-vertex/zai-org/glm-5.2-maas"},
                }
            ],
        }
    )


def test_replay_admits_only_owner_validated_configurations_and_selections():
    submitted, normalized = configuration("1.0.0"), configuration("1.0.1")
    selection = {"slot_id": "task", "declaration_ref": "control_context_assets.red-task"}
    requests = [{"participant_address": "agents.red-team-operator"}]
    results = [
        SimpleNamespace(
            input_digest=canonical_contract_digest(submitted),
            normalized=normalized.model_dump(mode="json"),
            contexts=[selection],
        )
    ]
    validator = ReplayedConfigurationValidator.from_results(requests, results).for_scenario(object())
    assert validator.validate_and_normalize(submitted) == normalized
    with pytest.raises(ValueError, match="not validated"):
        validator.validate_and_normalize(configuration("2.0.0"))
    accepted = SimpleNamespace(model_dump=lambda mode: selection)
    validator.validate_control_context_reference("agents.red-team-operator", accepted)
    with pytest.raises(ValueError, match="not validated"):
        validator.validate_control_context_reference("agents.blue-team-operator", accepted)
    with pytest.raises(ValueError, match="do not match"):
        ReplayedConfigurationValidator.from_results(requests * 2, results)
    assert canonical_json_digest(selection)


def _manifest(name: str, registry: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(name=name, version="1"),
        schema_version="v1",
        model_dump=lambda mode: {"name": name},
        configuration_registry=registry,
    )


def _descriptor(address: str, condition: str, value: str) -> SimpleNamespace:
    target = SimpleNamespace(plane="participant-implementation", participant_address=address, target_id="model")
    return SimpleNamespace(
        target=target, source_condition_id=condition, value=SimpleNamespace(model_dump=lambda mode: value)
    )


def test_admission_replays_one_owner_call_per_distinct_participant_override(monkeypatch):
    from shared.raes import experiment_admission as admission

    for name in ("AdmittedApparatusBindingModel", "AdmittedParticipantManifestReferenceModel"):
        monkeypatch.setattr(admission, name, lambda **fields: fields)
    monkeypatch.setattr(admission, "ExperimentManifestReferenceModel", SimpleNamespace(model_validate=dict))
    monkeypatch.setattr(admission, "TrialCompilationLimitsModel", lambda: None)
    monkeypatch.setattr(admission, "canonical_sdl_digest", lambda _family: SimpleNamespace(value="sha256:" + "2" * 64))
    owner = SimpleNamespace(validator_id="lilrae-opencode-request", validator_version="1")
    participant = _manifest("lilrae-opencode", SimpleNamespace(owner=owner))
    authority = SimpleNamespace(
        backend=_manifest("aptl"),
        processor=_manifest("reference"),
        participants=[SimpleNamespace(participant_address="agents.red", manifest=participant)],
        realization_envelope=SimpleNamespace(identity="envelope"),
        execution_authority="authority",
    )
    descriptors = [
        _descriptor("agents.red", "condition-1", "glm"),
        _descriptor("agents.red", "condition-2", "glm"),
        _descriptor("agents.blue", "condition-1", "other"),
    ]
    experiment = SimpleNamespace(
        family=object(),
        experiment=SimpleNamespace(
            binding_descriptors=SimpleNamespace(descriptors=descriptors),
            apparatus_intent=SimpleNamespace(required_capabilities={"capability"}),
        ),
    )
    calls = []
    submitted = configuration("1.0.0")

    def validate(owner_id, family_digest, requests):
        calls.append((owner_id, family_digest, requests))
        return [
            SimpleNamespace(
                input_digest=canonical_contract_digest(submitted),
                normalized=submitted.model_dump(mode="json"),
                contexts=[],
            )
        ]

    context = admission._context(experiment, authority, validate)

    ((owner_id, family_digest, requests),) = calls
    assert (owner_id, family_digest) == ("lilrae-opencode-request@1", "sha256:" + "2" * 64)
    assert requests == [
        {
            "participant_address": "agents.red",
            "participant_manifest": {"name": "lilrae-opencode"},
            "overrides": [{"target_id": "model", "value": "glm"}],
        }
    ]
    replayed = context["participant_configuration_validators"][("lilrae-opencode-request", "1")]
    assert replayed.validate_and_normalize(submitted) == submitted
    with pytest.raises(ValueError, match="Unsupported participant configuration owner"):
        admission._context(experiment, authority)
