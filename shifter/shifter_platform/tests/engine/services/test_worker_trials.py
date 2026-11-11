"""One trial per worker: durable start, replay, stop, collection and receipts."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone

from tests.cms.test_runtime_plugins import tenant
from tests.engine.services.test_disposable_workers import apparatus, create

__all__ = ["apparatus", "tenant"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def staged(prefix="trial-inputs/attempt/"):
    from shared.worker_trial import StagedObject

    return {
        name: StagedObject(key=prefix + name, sha256=str(index) * 64, size_bytes=10 + index)
        for index, name in enumerate(("trial.json", "trial-unit.json", "scenario.sdl", "plan.json"), start=1)
    }


@pytest.fixture
def ready_worker(apparatus, monkeypatch):
    from engine.models import Range

    worker = create(apparatus)
    Range.objects.update(status="ready", provisioner_operation="raes-range:provision", provisioner_operation_id=uuid4())
    qualified = {"current": True}
    monkeypatch.setattr(
        "engine.services._worker_qualification.has_current_qualification", lambda _worker: qualified["current"]
    )
    return SimpleNamespace(apparatus=apparatus, worker_id=worker.worker_id, qualified=qualified)


def start(ready_worker, **kwargs):
    from engine.services import start_worker_trial

    return start_worker_trial(
        ready_worker.apparatus.credential,
        ready_worker.worker_id,
        owner_reference=kwargs.pop("owner_reference", ready_worker.worker_id),
        staged=kwargs.pop("staged", staged()),
        deadline=timezone.now() + timedelta(hours=1),
    )


def current_intent(trial_id):
    from engine.models import ProvisionerLaunchIntent, WorkerTrial

    trial = WorkerTrial.objects.get(pk=trial_id)
    return trial, ProvisionerLaunchIntent.objects.get(operation_id=trial.provisioner_operation_id)


def test_start_persists_one_trial_and_its_run_operation_before_launch(ready_worker):
    from engine.launch_intents import command_from_payload, validate_provisioner_command
    from engine.models import OperationInput, ProvisionerLaunchIntent, WorkerTrial
    from engine.services._worker_trials import validate_worker_trial_operation

    ready_worker.qualified["current"] = False
    with pytest.raises(ValueError, match="qualification"):
        start(ready_worker)
    ready_worker.qualified["current"] = True
    view = start(ready_worker)
    assert (view.state, view.operation, view.operation_finished) == ("pending", "run", False)
    trial, intent = current_intent(view.trial_id)
    assert intent.payload["resource"] == "worker-trial" and intent.payload["trial_id"] == str(trial.pk)
    command = command_from_payload({**intent.payload, "operation_id": str(intent.operation_id)})
    assert validate_provisioner_command(command)["trial_id"] == str(trial.pk)
    stored = OperationInput.objects.get(operation_id=intent.operation_id).envelope["payload"]
    assert (
        set(stored["staged"]) == {"trial.json", "trial-unit.json", "scenario.sdl", "plan.json"}
        and stored["stop"] is False
    )
    assert validate_worker_trial_operation(intent.payload, intent.operation_id) == trial

    # A replay returns the same trial; a different attempt or input conflicts and adds nothing.
    assert start(ready_worker).trial_id == view.trial_id
    with pytest.raises(ValueError, match="conflicts"):
        start(ready_worker, owner_reference=uuid4())
    with pytest.raises(ValueError, match="conflicts"):
        start(ready_worker, staged=staged("trial-inputs/other/"))
    assert (
        WorkerTrial.objects.count() == 1
        and ProvisionerLaunchIntent.objects.filter(payload__resource="worker-trial").count() == 1
    )


def test_stop_interrupts_run_and_the_interrupt_launches_collect_only(ready_worker):
    from engine.models import InterruptState, OperationInput
    from engine.services import collect_worker_trial
    from engine.services._worker_trials import enqueue_interrupted_worker_trial

    view = start(ready_worker)
    _trial, run = current_intent(view.trial_id)
    assert collect_worker_trial(ready_worker.apparatus.credential, ready_worker.worker_id, stop=True).stop_requested
    run.refresh_from_db()
    assert run.interrupt_state == InterruptState.REQUESTED
    assert enqueue_interrupted_worker_trial(run)
    trial, collect = current_intent(view.trial_id)
    assert (trial.provisioner_operation, collect.payload["operation"]) == ("collect", "collect")
    assert OperationInput.objects.get(operation_id=collect.operation_id).envelope["payload"]["stop"] is True
    # A replayed interrupt for the superseded run launches nothing more.
    assert enqueue_interrupted_worker_trial(run)
    assert current_intent(view.trial_id)[1].operation_id == collect.operation_id


def test_receipts_apply_only_to_the_current_operation_and_failure_allows_collection(ready_worker):
    from engine.models import OperationResultDisposition, OperationResultInbox, WorkerTrial
    from engine.services import collect_worker_trial
    from engine.services._worker_trials import apply_worker_trial_result

    view = start(ready_worker)
    trial, run = current_intent(view.trial_id)
    archive = {"key": f"trial-exports/{trial.pk}/x/run.tar.gz", "sha256": "a" * 64, "size_bytes": 5}
    receipt = {"trial_id": str(trial.pk), "state": "exited", "exit_code": 0, "sealed": True, "archive": archive}
    stale = SimpleNamespace(operation_id=uuid4(), request_id=trial.generation, result_kind="TERMINAL_SUCCESS")
    assert apply_worker_trial_result(stale, receipt)[0] == OperationResultDisposition.REJECTED_STALE
    current = SimpleNamespace(
        operation_id=run.operation_id, request_id=trial.generation, result_kind="TERMINAL_SUCCESS"
    )
    foreign = {**receipt, "trial_id": str(uuid4())}
    assert apply_worker_trial_result(current, foreign)[0] == OperationResultDisposition.REJECTED_OWNERSHIP
    exited = {"trial_id": str(trial.pk), "state": "exited", "exit_code": 3, "sealed": False, "archive": None}
    assert apply_worker_trial_result(current, exited)[0] == OperationResultDisposition.APPLIED
    failed = SimpleNamespace(operation_id=run.operation_id, request_id=trial.generation, result_kind="TERMINAL_FAILURE")
    assert apply_worker_trial_result(failed, {})[0] == OperationResultDisposition.APPLIED
    observed = WorkerTrial.objects.get(pk=trial.pk)
    # The failure keeps the observed exit, so the exit-code constraint still holds.
    assert (observed.state, observed.exit_code, observed.operation_failed) == ("exited", 3, True)

    # The run is not finished until its terminal result is applied; then collect may launch.
    collect_worker_trial(ready_worker.apparatus.credential, ready_worker.worker_id)
    assert current_intent(view.trial_id)[0].provisioner_operation == "run"
    OperationResultInbox.objects.create(
        operation_id=run.operation_id,
        request_id=trial.generation,
        resource="worker-trial",
        operation="run",
        contract_version="1",
        envelope={},
        payload_digest="sha256:" + "0" * 64,
        result_kind="TERMINAL_FAILURE",
        disposition=OperationResultDisposition.APPLIED,
    )
    collect_worker_trial(ready_worker.apparatus.credential, ready_worker.worker_id)
    trial, collect = current_intent(view.trial_id)
    assert collect.payload["operation"] == "collect"
    done = SimpleNamespace(
        operation_id=collect.operation_id, request_id=trial.generation, result_kind="TERMINAL_SUCCESS"
    )
    assert apply_worker_trial_result(done, receipt)[0] == OperationResultDisposition.APPLIED
    trial.refresh_from_db()
    assert (trial.state, trial.exit_code, trial.sealed, trial.archive) == ("exited", 0, True, archive)
    assert not trial.operation_failed


def test_exhausted_dispatch_fails_only_the_current_trial_operation(ready_worker):
    from engine.launch_intents_failure import fail_current_provisioner_operation
    from engine.models import WorkerTrial

    view = start(ready_worker)
    _trial, run = current_intent(view.trial_id)
    assert not fail_current_provisioner_operation(run.payload, uuid4())
    assert fail_current_provisioner_operation(run.payload, run.operation_id)
    assert WorkerTrial.objects.get(pk=view.trial_id).operation_failed
