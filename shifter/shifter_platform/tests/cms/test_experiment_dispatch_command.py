"""The experiment_dispatch command routes each operation to its service and prints one JSON line per entry."""

import json
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cms.management.commands import experiment_dispatch as command
from cms.services._experiment_dispatch import DispatchStep
from shared.exceptions import CMSError

_STEP = DispatchStep(
    plan_entry_id="entry-1",
    execution_attempt_id=None,
    worker_id=None,
    trial_state=None,
    collected=False,
    cleanup_recorded=False,
    action="none",
)


@pytest.fixture
def services(monkeypatch):
    """Record each service call instead of running the coordinator."""
    calls = []

    def record(name, result):
        def service(*args, **kwargs):
            calls.append((name, kwargs))
            return result

        return service

    monkeypatch.setattr(command, "credential_from_file", lambda path: "credential")
    monkeypatch.setattr(command, "hierarchy_target_scope", lambda kind, scope_id: (kind, scope_id))
    monkeypatch.setattr(command, "list_experiment_entries", record("show", [{"plan_entry_id": "entry-1"}]))
    monkeypatch.setattr(command, "stop_experiment_dispatch", record("stop", [_STEP]))
    monkeypatch.setattr(command, "start_experiment_dispatch", record("start", [_STEP]))
    monkeypatch.setattr(command, "reconcile_experiment_dispatch", record("reconcile", [_STEP]))
    return calls


def _run(operation, *, scope=True):
    output = StringIO()
    options = {"credential_file": "proof", "organization": uuid4(), "batch": uuid4(), "stdout": output}
    if scope:
        options.update(scope_kind="workspace", scope_id=uuid4())
    call_command("experiment_dispatch", operation, **options)
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize(
    ("operation", "service", "collect_only"),
    [
        ("show", "show", None),
        ("stop", "stop", None),
        ("start", "start", None),
        ("reconcile", "reconcile", False),
        ("collect", "reconcile", True),
    ],
)
def test_each_operation_calls_its_service_and_prints_each_entry(services, operation, service, collect_only):
    rows = _run(operation)
    assert [row["plan_entry_id"] for row in rows] == ["entry-1"]
    assert [name for name, _ in services] == [service]
    if collect_only is not None:
        assert services[0][1]["collect_only"] is collect_only


def test_a_worker_operation_without_a_scope_or_a_refused_service_fails_closed(services, monkeypatch):
    with pytest.raises(CommandError, match="Experiment dispatch start failed"):
        _run("start", scope=False)

    def refused(*args, **kwargs):
        raise CMSError("Experiment operation unavailable")

    monkeypatch.setattr(command, "stop_experiment_dispatch", refused)
    with pytest.raises(CommandError, match="Experiment dispatch stop failed"):
        _run("stop")
    assert services == []
