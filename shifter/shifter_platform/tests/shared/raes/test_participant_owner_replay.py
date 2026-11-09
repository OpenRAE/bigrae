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
                {"target_id": "model", "value_type": "string", "origin": "override",
                 "value": {"kind": "literal", "value": "google-vertex/zai-org/glm-5.2-maas"}}
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
