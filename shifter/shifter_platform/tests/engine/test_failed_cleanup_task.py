"""Failed cleanup retries require terminal provider evidence and exact workload identity."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.services._failed_cleanup_task import retire_failed_cleanup_task
from shared.cloud.exceptions import CloudTaskError


@pytest.fixture
def task(settings, monkeypatch):
    settings.CLOUD_PROVIDER = "gcp"
    workload = {
        "provider": "gcp",
        "namespace": "synthetic-jobs",
        "job_name": "synthetic-cleanup",
        "task_identity": "synthetic-intent",
        "image": "example.test/task@sha256:" + "a" * 64,
        "container_name": "provisioner",
        "service_account_name": "synthetic-worker",
        "command": ["raes-range", "destroy"],
    }
    intent = SimpleNamespace(
        executing_workload=workload, task_ref="synthetic-jobs/synthetic-cleanup", status="SUCCEEDED"
    )
    runner = Mock()
    monkeypatch.setattr("engine.services._failed_cleanup_task.get_task_runner", lambda: runner)
    return intent, runner


@pytest.mark.parametrize("state", ["RUNNING", "SUBMITTED", "SUCCEEDED", "UNKNOWN"])
def test_active_unknown_or_successful_task_cannot_authorize_retry(task, state):
    intent, runner = task
    runner.get_task_status.return_value = {"status": state} if state is not None else None
    assert not retire_failed_cleanup_task(intent)
    runner.delete_completed_task.assert_not_called()


def test_failed_task_requires_identity_checked_terminal_removal(task):
    intent, runner = task
    runner.get_task_status.return_value = {"status": "FAILED"}
    assert retire_failed_cleanup_task(intent)
    runner.delete_completed_task.assert_called_once_with(
        "synthetic-jobs",
        intent.task_ref,
        {
            key: intent.executing_workload[key]
            for key in ["task_identity", "image", "container_name", "service_account_name", "command"]
        },
    )


@pytest.mark.parametrize("failure", ["observe", "identity"])
def test_provider_outage_or_identity_refusal_retains_the_attempt(task, failure):
    intent, runner = task
    runner.get_task_status.return_value = {"status": "FAILED"}
    method = runner.get_task_status if failure == "observe" else runner.delete_completed_task
    method.side_effect = CloudTaskError("Synthetic provider failure")
    assert not retire_failed_cleanup_task(intent)


@pytest.mark.parametrize(
    "field,value", [("provider", "aws"), ("namespace", "other"), ("image", ""), ("command", "invalid")]
)
def test_changed_or_incomplete_workload_does_not_reach_the_provider(task, field, value):
    intent, runner = task
    intent.executing_workload[field] = value
    assert not retire_failed_cleanup_task(intent)
    runner.get_task_status.assert_not_called()


@pytest.mark.parametrize("delivery", ["PENDING", "RUNNING", "DLQ"])
def test_undelivered_attempt_cannot_be_replaced(task, delivery):
    intent, runner = task
    intent.status = delivery
    runner.get_task_status.return_value = {"status": "FAILED"}
    assert not retire_failed_cleanup_task(intent)
    runner.get_task_status.assert_not_called()


def test_default_service_account_matches_the_effective_kubernetes_identity(task):
    intent, runner = task
    intent.executing_workload["service_account_name"] = ""
    runner.get_task_status.return_value = {"status": "FAILED"}
    assert retire_failed_cleanup_task(intent)
    assert runner.delete_completed_task.call_args.args[2]["service_account_name"] == "default"


@pytest.mark.parametrize("verified_absence", [False, True])
def test_missing_job_requires_provider_verification_of_complete_absence(task, verified_absence):
    intent, runner = task
    runner.get_task_status.return_value = None
    if not verified_absence:
        runner.delete_completed_task.side_effect = CloudTaskError("Absence is unavailable")
    assert retire_failed_cleanup_task(intent) is verified_absence
    runner.delete_completed_task.assert_called_once()
