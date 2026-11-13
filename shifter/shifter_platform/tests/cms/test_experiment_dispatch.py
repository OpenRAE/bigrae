"""The coordinator advances each admitted entry once, from stored state only."""

import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.core.exceptions import ObjectDoesNotExist

from tests.cms.experiment_admission_fixtures import admit, experiment_inputs
from tests.cms.test_runtime_plugins import tenant
from tests.cms.test_trial_archives import custody
from tests.shared.raes.test_trial_archive import trial_record_archive

__all__ = ["custody", "experiment_inputs", "tenant"]
pytestmark = pytest.mark.django_db


@dataclass
class FakeEngine:
    """The Engine worker and worker-trial facade, held in memory."""

    workers: dict[UUID, SimpleNamespace] = field(default_factory=dict)
    trials: dict[UUID, SimpleNamespace] = field(default_factory=dict)
    holds: dict[UUID, list[SimpleNamespace]] = field(default_factory=dict)
    capacity: int = 10
    collect_requests: list[tuple[UUID, bool]] = field(default_factory=list)

    def create_disposable_worker(self, credential, *, scope, worker_id, experiment_id, trial_id):
        if worker_id not in self.workers:
            if len(self.workers) >= self.capacity:
                raise ValueError("Worker capacity is unavailable")
            self.workers[worker_id] = SimpleNamespace(
                status="provisioning", qualified=False, retiring=False, retired=False, trial=trial_id
            )
        return self.workers[worker_id]

    def get_disposable_worker(self, credential, worker_id):
        return self.workers[worker_id]

    def qualify_disposable_worker(self, credential, worker_id):
        worker = self.workers[worker_id]
        if worker.status != "ready":
            raise ValueError("Worker observation is unavailable")
        worker.qualified = True

    def acquire_worker_hold(self, credential, worker_id, *, reason):
        self.holds.setdefault(worker_id, []).append(SimpleNamespace(hold_id=worker_id, reason=reason, released=False))

    def list_worker_holds(self, credential, worker_id):
        return tuple(hold for hold in self.holds.get(worker_id, []) if not hold.released)

    def release_worker_hold(self, credential, hold_id):
        for hold in self.holds[hold_id]:
            hold.released = True

    def retire_disposable_worker(self, credential, worker_id):
        if any(not hold.released for hold in self.holds.get(worker_id, [])):
            raise ValueError("Worker hold blocks retirement")
        self.workers[worker_id].retiring = True

    def start_worker_trial(self, credential, worker_id, *, owner_reference, staged, deadline):
        if worker_id in self.trials:
            raise AssertionError("a second trial start")
        if not self.workers[worker_id].qualified:
            raise ValueError("Worker qualification is not current")
        self.trials[worker_id] = SimpleNamespace(
            state="pending",
            sealed=False,
            archive=None,
            staged=staged,
            operation="run",
            operation_finished=False,
            operation_failed=False,
            overdue=False,
        )

    def get_worker_trial(self, credential, worker_id):
        if worker_id not in self.trials:
            raise ObjectDoesNotExist
        return self.trials[worker_id]

    def collect_worker_trial(self, credential, worker_id, *, stop=False):
        if worker_id not in self.trials:
            raise ObjectDoesNotExist
        self.collect_requests.append((worker_id, stop))


@pytest.fixture
def dispatch(experiment_inputs, custody, monkeypatch):
    import engine.services

    engine_fake = FakeEngine()
    for name in (
        "create_disposable_worker",
        "get_disposable_worker",
        "acquire_worker_hold",
        "list_worker_holds",
        "release_worker_hold",
        "retire_disposable_worker",
        "start_worker_trial",
        "qualify_disposable_worker",
        "get_worker_trial",
        "collect_worker_trial",
    ):
        monkeypatch.setattr(engine.services, name, getattr(engine_fake, name))
    storage = custody[2]
    monkeypatch.setattr("cms.services._experiment_dispatch.get_object_storage", lambda: storage)
    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    return SimpleNamespace(
        engine=engine_fake, storage=storage, batch=batch, actor=actor, organization=organization, scope=object()
    )


def run(dispatch, operation="reconcile", **options):
    from cms.services import reconcile_experiment_dispatch, start_experiment_dispatch, stop_experiment_dispatch

    args = (dispatch.actor.credential, dispatch.organization.uuid, dispatch.batch.id)
    if operation == "start":
        return start_experiment_dispatch(*args, scope=dispatch.scope)
    if operation == "stop":
        return stop_experiment_dispatch(*args)
    return reconcile_experiment_dispatch(*args, scope=dispatch.scope, **options)


def finish(dispatch, worker_id, entry, *, attempt_id, run_id=None, run_status=None, limitations=()):
    """The worker exported a sealed archive for the expected attempt and trial SDL."""
    from shared.raes.experiment_dispatch_inputs import trial_scenario_bytes

    inputs = dispatch.batch.inputs
    scenario = "sha256:" + hashlib.sha256(trial_scenario_bytes(inputs, entry.plan_entry_id)).hexdigest()
    raw = trial_record_archive(
        run_id=run_id or entry.run_id,
        attempt_id=attempt_id,
        scenario=scenario,
        run_status=run_status,
        limitations=limitations,
    )
    key = f"trial-exports/{worker_id}/op/run.tar.gz"
    dispatch.storage.objects[("bigrae-assets", key)] = raw
    trial = dispatch.engine.trials[worker_id]
    trial.state, trial.sealed, trial.operation_finished = "exited", True, True
    trial.archive = {"key": key, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def test_dispatch_runs_each_trial_once_through_collection_retirement_and_cleanup(dispatch, settings):
    from cms.models import ExperimentEntry

    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    steps = run(dispatch, "start")
    claimed = [step for step in steps if step.execution_attempt_id]
    assert len(claimed) == dispatch.batch.inputs["resource_limits"]["requested_concurrency"]
    assert [step.action for step in claimed] == ["waiting-for-worker"]
    # A second start and a restart reconcile neither claim nor create more workers.
    run(dispatch, "start")
    assert len(dispatch.engine.workers) == 1

    worker_id = next(iter(dispatch.engine.workers))
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["waiting-for-worker"]
    dispatch.engine.workers[worker_id].status = "ready"
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["trial-started"]
    assert dispatch.engine.workers[worker_id].qualified
    staged = dispatch.engine.trials[worker_id].staged
    # #2906: the trial unit is the only staged copy of the admitted plan.
    assert set(staged) == {"trial.json", "trial-unit.json", "scenario.sdl"}
    assert all(("bigrae-assets", item.key) in dispatch.storage.objects for item in staged.values())
    from shifter_adapter_sdk.trial import TrialInput

    control = TrialInput.model_validate_json(dispatch.storage.objects[("bigrae-assets", staged["trial.json"].key)])
    unit_bytes = dispatch.storage.objects[("bigrae-assets", staged["trial-unit.json"].key)]
    scenario_bytes = dispatch.storage.objects[("bigrae-assets", staged["scenario.sdl"].key)]
    assert control.unit_sha256 == hashlib.sha256(unit_bytes).hexdigest()
    assert control.scenario_sha256 == hashlib.sha256(scenario_bytes).hexdigest()
    unit = json.loads(unit_bytes)
    assert unit["plan"] == dispatch.batch.inputs["plan"]
    assert unit["snapshot"] == json.loads(scenario_bytes)
    assert unit["material"] == {
        name: dispatch.batch.inputs[name]
        for name in ("experiment", "task", "capture_specs", "authority")
    }
    assert (
        "sha256:" + hashlib.sha256(scenario_bytes).hexdigest()
        == dispatch.batch.inputs["snapshot_digests"][unit["plan_entry_id"]]
    )
    # A concurrent or repeated stager reuses the persisted deadline and the identical objects.
    from cms.services._experiment_dispatch import stage_trial

    entry = ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}")
    again, _deadline = stage_trial(dispatch.actor.credential, dispatch.organization.uuid, dispatch.batch.inputs, entry)
    assert again == staged
    # The coordinator restarted: the stored trial is running, so nothing starts again.
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["running"]

    entry = ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}")
    finish(dispatch, worker_id, entry, attempt_id=str(entry.token))
    assert [step.action for step in run(dispatch, collect_only=True) if step.execution_attempt_id] == ["collected"]
    entry.refresh_from_db()
    assert entry.receipt_id is not None and entry.state == "finished"

    # Failed teardown: retirement is requested, but cleanup waits for verified absence.
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["retiring"]
    assert all(hold.released for hold in dispatch.engine.holds[worker_id])
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["waiting-for-cleanup"]
    dispatch.engine.workers[worker_id].retired = True
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["cleanup-recorded"]
    entry.refresh_from_db()
    assert entry.cleanup_receipt_json


def test_failed_collection_keeps_the_worker_and_shows_the_attempt_not_collected(dispatch, settings):
    from cms.models import ExperimentEntry

    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    run(dispatch, "start")
    worker_id = next(iter(dispatch.engine.workers))
    dispatch.engine.workers[worker_id].status = "ready"
    run(dispatch)
    entry = ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}")
    finish(dispatch, worker_id, entry, attempt_id=str(entry.token), run_id="another-run")
    # The refused archive is reported for its entry; the pass still advances the others.
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["error"]
    entry.refresh_from_db()
    assert entry.receipt_id is None
    assert not dispatch.engine.workers[worker_id].retiring
    assert all(not hold.released for hold in dispatch.engine.holds[worker_id])


def test_stop_fences_unstarted_entries_and_new_claims(dispatch, settings):
    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    run(dispatch, "start")
    worker_id = next(iter(dispatch.engine.workers))
    assert [step.action for step in run(dispatch, "stop") if step.execution_attempt_id] == ["not-started"]
    dispatch.engine.workers[worker_id].status = "ready"
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["stopped"]
    assert worker_id not in dispatch.engine.trials
    run(dispatch, "start")
    assert len(dispatch.engine.workers) == 1


def test_lost_and_unsealed_runs_are_collected_without_a_new_start(dispatch, settings):
    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    run(dispatch, "start")
    worker_id = next(iter(dispatch.engine.workers))
    dispatch.engine.workers[worker_id].status = "ready"
    run(dispatch)
    trial = dispatch.engine.trials[worker_id]
    trial.overdue = True
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["recovery-requested"]
    trial.operation_finished, trial.operation_failed = True, True
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["collect-requested"]
    trial.state, trial.exit_code, trial.operation, trial.operation_failed = "exited", 1, "collect", False
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["not-sealed"]
    assert dispatch.engine.collect_requests == [(worker_id, True), (worker_id, False)]
    # An unsealed trial is a failed attempt with no data: its worker retires and cleanup follows.
    from cms.models import ExperimentEntry

    assert ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}").state == "failed"
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["retiring"]
    dispatch.engine.workers[worker_id].retired = True
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["cleanup-recorded"]


def test_worker_capacity_refusal_leaves_the_claim_for_reconcile(dispatch, settings):
    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    dispatch.engine.capacity = 0
    assert [step.action for step in run(dispatch, "start") if step.execution_attempt_id] == ["waiting-for-capacity"]
    dispatch.engine.capacity = 1
    assert [step.action for step in run(dispatch) if step.execution_attempt_id] == ["worker-created"]
    assert len(dispatch.engine.workers) == 1


def test_a_trial_with_missing_data_fails_and_gets_one_fresh_trial_on_a_new_worker(dispatch, settings, monkeypatch):
    from cms.models import ExperimentEntry
    from cms.services import _experiment_replacement

    settings.STORAGE_BUCKET_NAME = "bigrae-assets"
    # The admitted plan's replacement policy authorizes one fresh trial for a failed trial.
    monkeypatch.setattr(_experiment_replacement, "_allowed", lambda _inputs, ordinal: ordinal <= 1)
    run(dispatch, "start")
    worker_id = next(iter(dispatch.engine.workers))
    dispatch.engine.workers[worker_id].status = "ready"
    run(dispatch)
    failed = ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}")
    gap = [{"code": "required-data-missing", "detail": "raw chat of agents.blue is missing"}]
    finish(dispatch, worker_id, failed, attempt_id=str(failed.token), run_status="completed", limitations=gap)
    run(dispatch)  # collected
    failed.refresh_from_db()
    assert failed.state == "failed"
    run(dispatch)  # retiring
    dispatch.engine.workers[worker_id].retired = True
    run(dispatch)  # cleanup recorded

    actions = {(step.plan_entry_id, step.execution_attempt_id): step.action for step in run(dispatch)}
    assert actions[(failed.plan_entry_id, str(failed.token))] == "rerun-recorded"
    fresh = ExperimentEntry.objects.get(replaces=failed)
    assert (fresh.plan_entry_id, fresh.run_id, fresh.replacement_ordinal) == (failed.plan_entry_id, failed.run_id, 1)

    # The next pass claims the fresh trial and creates a new worker; the failed attempt stays recorded.
    steps = [step for step in run(dispatch) if step.plan_entry_id == failed.plan_entry_id]
    assert sorted(step.action for step in steps) == ["replaced", "worker-created"]
    fresh.refresh_from_db()
    assert fresh.token != failed.token and len(dispatch.engine.workers) == 2

    # The batch report shows the failed attempt, its archive facts, and the fresh trial that replaces it.
    from cms.services import list_experiment_entries

    rows = [
        row
        for row in list_experiment_entries(dispatch.actor.credential, dispatch.organization.uuid, dispatch.batch.id)
        if row["plan_entry_id"] == failed.plan_entry_id
    ]
    assert [(row["attempt"], row["state"], row["run_status"], row["data_complete"]) for row in rows] == [
        (0, "failed", "completed", False),
        (1, "claimed", None, None),
    ]
    assert rows[1]["replaces_attempt_id"] == str(failed.token)

    # The policy allows one fresh trial: a second failure of the same entry gets none.
    fresh.state = "failed"
    args = (dispatch.actor.credential, dispatch.organization.uuid, dispatch.batch.inputs)
    assert _experiment_replacement.rerun_failed_entry(*args, fresh) == "none"


@pytest.mark.parametrize("status", ["failed", "destroying", "destroyed"])
def test_failed_worker_setup_waits_for_verified_cleanup_before_replacement(dispatch, monkeypatch, status):
    from cms.models import ExperimentEntry
    from cms.services import _experiment_replacement

    monkeypatch.setattr(_experiment_replacement, "_allowed", lambda _inputs, ordinal: ordinal <= 1)
    run(dispatch, "start")
    worker_id = next(iter(dispatch.engine.workers))
    worker = dispatch.engine.workers[worker_id]
    worker.status = status
    failed = ExperimentEntry.objects.get(worker_ref=f"worker:{worker_id}")

    assert [s.action for s in run(dispatch) if s.worker_id == str(worker_id)] == ["worker-setup-failed"]
    failed.refresh_from_db()
    assert failed.state == "failed" and failed.receipt_id is None
    assert worker_id not in dispatch.engine.trials
    assert [s.action for s in run(dispatch) if s.worker_id == str(worker_id)] == ["retiring"]
    assert [s.action for s in run(dispatch) if s.worker_id == str(worker_id)] == ["waiting-for-cleanup"]
    assert not ExperimentEntry.objects.filter(replaces=failed).exists()
    assert not failed.cleanup_receipt_json

    worker.retired = True
    assert [s.action for s in run(dispatch) if s.worker_id == str(worker_id)] == ["cleanup-recorded"]
    assert [s.action for s in run(dispatch) if s.worker_id == str(worker_id)] == ["rerun-recorded"]
    fresh = ExperimentEntry.objects.get(replaces=failed)
    assert fresh.state == "pending" and fresh.token is None
    failed.refresh_from_db()
    assert failed.state == "failed" and failed.receipt_id is None and failed.cleanup_receipt_json


def test_the_replacement_policy_bounds_fresh_trials_for_a_failed_trial():
    from cms.services._experiment_replacement import _allowed

    inputs = {"plan": {"replacement_policy": {"max_replacements": 2, "replace_on": ["failed", "invalidated"]}}}
    assert _allowed(inputs, 1) and _allowed(inputs, 2) and not _allowed(inputs, 3)
    assert not _allowed({"plan": {"replacement_policy": {"max_replacements": 2, "replace_on": ["invalidated"]}}}, 1)
    assert not _allowed({"plan": {}}, 1)
