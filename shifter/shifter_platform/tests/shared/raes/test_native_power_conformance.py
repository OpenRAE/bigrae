"""Released validators own the selected carrier checks, not a broader profile claim."""

import json

import pytest
from raes_conformance.conformance import fixtures_root, validate_contract_payload

_CARRIERS = (
    "backend-manifest-v2",
    "participant-control-occurrence-v1",
    "participant-control-occurrence-v2",
    "participant-crossing-occurrence-v1",
    "participant-episode-state-envelope-v1",
    "participant-episode-history-event-stream-v1",
    "participant-behavior-history-event-stream-v1",
)


@pytest.mark.parametrize("contract", _CARRIERS)
def test_selected_carriers_obey_the_released_positive_and_negative_corpus(contract):
    roots = [path for path in fixtures_root().glob(f"**/{contract}") if path.is_dir()]
    assert len(roots) == 1
    positives = list((roots[0] / "valid").glob("*.json"))
    negatives = list((roots[0] / "invalid").glob("*.json"))
    assert positives and negatives
    for expected, paths in ((True, positives), (False, negatives)):
        for path in paths:
            diagnostics = validate_contract_payload(contract, json.loads(path.read_text()))
            assert (not diagnostics) is expected, (contract, path.name, tuple(d.code for d in diagnostics))


def assert_native_control_records_conform(owner):
    """Validate the real authenticated owner's manifest, episode and actual history."""
    from raes_backend_protocols.manifest import backend_manifest_payload

    manifest = backend_manifest_payload(owner._candidate.target.manifest)
    diagnostics = validate_contract_payload("backend-manifest-v2", manifest)
    assert not diagnostics, tuple(d.code for d in diagnostics)
    snapshot = owner._owner.snapshot
    for field, contract in (
        ("participant_control_history", "participant-control-occurrence-v2"),
        ("participant_crossing_history", "participant-crossing-occurrence-v1"),
    ):
        histories = getattr(snapshot, field)
        assert histories
        for records in histories.values():
            assert records
            for record in records:
                if field == "participant_control_history":
                    assert record["schema_version"] == "2.0.0"
                diagnostics = validate_contract_payload(contract, record)
                assert not diagnostics, (contract, tuple(d.code for d in diagnostics))
    for episode in snapshot.participant_episode_results.values():
        diagnostics = validate_contract_payload("participant-episode-state-envelope-v1", episode)
        assert not diagnostics, tuple(d.code for d in diagnostics)
    for field, contract in (
        ("participant_episode_history", "participant-episode-history-event-stream-v1"),
        ("participant_behavior_history", "participant-behavior-history-event-stream-v1"),
    ):
        for records in getattr(snapshot, field).values():
            diagnostics = validate_contract_payload(contract, list(records))
            assert not diagnostics, (contract, tuple(d.code for d in diagnostics))
