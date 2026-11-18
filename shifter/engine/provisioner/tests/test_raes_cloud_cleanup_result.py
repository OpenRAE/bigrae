"""Cloud failure evidence must cross the result boundary without releasing custody."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from shared.operation_results import ResultStep, parse_result_payload

from raes_range_cloud import restore_cloud_projects


@pytest.mark.parametrize("count", [1, 2])
def test_incomplete_restoration_crosses_the_result_parser_without_private_errors(count, caplog):
    projects = []
    for _ in range(count):
        lease = SimpleNamespace(
            lease_id=uuid4(),
            baseline=SimpleNamespace(registration_id=uuid4(), state_digest="sha256:" + "a" * 64),
        )
        projects.append((SimpleNamespace(lease=lease), None, {}))
    cloud = SimpleNamespace(projects=projects, destroy=Mock(side_effect=ValueError("SYNTHETIC_PRIVATE_MARKER")))
    inventory = {"outcome": "VERIFIED_ABSENT", "residual_categories": [], "scope": {"range_id": 7}}
    result = restore_cloud_projects(cloud, inventory)
    parsed = parse_result_payload(
        "raes-range",
        "destroy",
        step=ResultStep.RAES_TERMINAL_DESTROYED,
        payload={"raes_status": "succeeded", "cleanup_inventory": result},
    )["cleanup_inventory"]
    assert parsed["outcome"] == "INCOMPLETE"
    assert parsed["residual_categories"] == [{"category": "cloud-projects", "count": count}]
    assert len(parsed["scope"]["gcp_projects"]) == count
    for proof, (work, _, _) in zip(parsed["scope"]["gcp_projects"], projects, strict=True):
        assert proof["outcome"] == "incomplete"
        assert proof["lease_id"] == str(work.lease.lease_id)
        assert proof["registration_id"] == str(work.lease.baseline.registration_id)
        assert proof["baseline_state_digest"] == work.lease.baseline.state_digest
    assert "SYNTHETIC_PRIVATE_MARKER" not in json.dumps(parsed)
    assert "SYNTHETIC_PRIVATE_MARKER" not in caplog.text
    assert "exc_type=ValueError" in caplog.text
    assert inventory["outcome"] == "VERIFIED_ABSENT"


def test_incomplete_vm_inventory_cannot_claim_cloud_restoration():
    cloud = SimpleNamespace(destroy=Mock())
    inventory = {"outcome": "INCOMPLETE", "residual_categories": [], "scope": {}}
    assert restore_cloud_projects(cloud, inventory) is inventory
    cloud.destroy.assert_not_called()
