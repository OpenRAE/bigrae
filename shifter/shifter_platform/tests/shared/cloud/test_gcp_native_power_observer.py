"""Exercise the read-only provider wire at the exact native cessation boundary."""

import io
import json
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest

from shared.cloud.native_power_readback import GCENativePowerObserver
from shared.native_participant import NativePowerInvocationGrant
from shared.native_power import GcePersistentDiskIdentity, GcePowerIncarnation, GcePowerTarget


@pytest.fixture
def observation():
    grant = NativePowerInvocationGrant(
        invocation_id=uuid4(),
        operation_id=uuid4(),
        resource_generation=uuid4(),
        verb="pause",
        member_ref="provision.node.web#0",
        attempt_id=uuid4(),
        target=GcePowerTarget("gce", "synthetic-project", "us-central1-a", "synthetic-vm", "standard"),
        incarnation=GcePowerIncarnation("123", (GcePersistentDiskIdentity("synthetic-disk", "456"),)),
    )
    value = {
        "items": [
            {
                "name": "operation-synthetic",
                "clientOperationId": str(grant.invocation_id),
                "operationType": "stop",
                "targetId": "123",
                "status": "DONE",
                "targetLink": "https://compute.googleapis.com/compute/v1/projects/synthetic-project/zones/us-central1-a/instances/synthetic-vm",
            }
        ]
    }
    return grant, value


def observe(grant, payload, *, status=200):
    response = Mock(status_code=status, raw=io.BytesIO(payload))
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response

    @contextmanager
    def factory():
        yield session

    return GCENativePowerObserver(session_factory=factory).completed_call(grant), session


@pytest.mark.parametrize("verb", ["pause", "resume"])
def test_only_exact_completed_request_establishes_call_cessation(observation, verb):
    from dataclasses import replace

    grant, value = observation
    grant = replace(grant, verb=verb)
    value["items"][0]["operationType"] = "stop" if verb == "pause" else "start"
    result, session = observe(grant, json.dumps(value).encode())
    assert result == "projects/synthetic-project/zones/us-central1-a/operations/operation-synthetic"
    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert args == (
        "https://compute.googleapis.com/compute/v1/projects/synthetic-project/zones/us-central1-a/operations",
    )
    assert kwargs["params"]["filter"] == f'clientOperationId = "{grant.invocation_id}"'
    assert kwargs["params"]["maxResults"] == 2
    assert kwargs["timeout"] == (1, 2)
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    session.post.assert_not_called()
    session.delete.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "next-page",
        "pending",
        "request",
        "verb",
        "target-id",
        "target-name",
        "foreign-origin",
        "malformed-id",
        "bad-name",
        "bad-json",
        "oversized",
        "duplicate-json-key",
        "denied",
    ],
)
def test_absence_ambiguity_or_wrong_incarnation_retains_uncertainty(observation, fault):
    grant, original = observation
    value = deepcopy(original)
    item = value["items"][0]
    if fault == "missing":
        value = {}
    elif fault == "duplicate":
        value["items"].append(deepcopy(item))
    elif fault == "next-page":
        value["nextPageToken"] = "more"
    elif fault == "pending":
        item["status"] = "RUNNING"
    elif fault == "request":
        item["clientOperationId"] = str(uuid4())
    elif fault == "verb":
        item["operationType"] = "start"
    elif fault == "target-id":
        item["targetId"] = "124"
    elif fault == "target-name":
        item["targetLink"] += "-replacement"
    elif fault == "foreign-origin":
        item["targetLink"] = item["targetLink"].replace("compute.googleapis.com", "foreign.test")
    elif fault == "malformed-id":
        item["targetId"] = True
    elif fault == "bad-name":
        item["name"] = "../foreign"
    payload = json.dumps(value).encode()
    if fault == "bad-json":
        payload = b"private provider diagnostics"
    elif fault == "oversized":
        payload = b" " * 32_769 + payload
    elif fault == "duplicate-json-key":
        payload = payload[:-1] + b', "items": []}'
    result, _ = observe(grant, payload, status=403 if fault == "denied" else 200)
    assert result is None


def test_transport_failure_is_unknown_without_disclosing_the_provider_error(observation):
    @contextmanager
    def unavailable():
        raise RuntimeError("synthetic private credential diagnostic")
        yield  # pragma: no cover

    assert GCENativePowerObserver(session_factory=unavailable).completed_call(observation[0]) is None
