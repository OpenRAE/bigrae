# Experiment dispatch

Reference for dispatch, trial control, collection, and cleanup contracts.

`cms.services` runs a retained batch on disposable workers.
The [design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/parallel-trial-dispatch-design-2743.md) records the boundaries and controls.

## Services

| Service | Behavior |
| --- | --- |
| `start_experiment_dispatch` | Claims entries, creates workers, reconciles |
| `reconcile_experiment_dispatch` | Advances each claimed entry by at most one step |
| `stop_experiment_dispatch` | Requests a stop for each running trial |

The worker identity is a UUID derived from the attempt token, so a lost response finds the same worker.
`claim_experiment_entry` bounds active claims to the batch concurrency.
`create_disposable_worker` bounds live workers to the worker policy and capacity reservations.

## Engine worker trials

`engine.services` owns one `WorkerTrial` row per worker.

| Service | Behavior |
| --- | --- |
| `start_worker_trial` | Records the trial and launches `worker-trial run`; an identical replay returns the same trial |
| `collect_worker_trial` | Launches `worker-trial collect`; with `stop`, interrupts a running `run` first |
| `get_worker_trial` | Returns state, exit code, seal, and archive reference |

Each operation records `range.manage` authority on the worker's range.
The launcher rechecks that authority before the provisioner starts.

## Staged inputs

The coordinator stages two objects under `trial-inputs/<attempt>/` in the assets bucket:

| Object | Content |
| --- | --- |
| `trial-unit.json` | The admitted plan, the plan entry ID, and the entry's instantiated snapshot |
| `trial.json` | Run ID, attempt ID, deadline, and the digest of `trial-unit.json` |

The deadline is the staging time plus the entry's admitted attempt timeout.
It is persisted on the entry before upload, so every stager writes identical bytes.
An existing object with different bytes is refused.
The worker image supplies the trial runtime and its environment pack.
The installed adapter that controls trials can also validate participant owners at admission.
The provisioner copies the objects to the worker's fixed trial input directory.

## Provisioner operations

The `restrict-provisioner-jobs` admission policy admits only the dispatched `worker-trial` argument form.
That form is `run` or `collect` with UUID `--request-id`, `--trial-id`, and `--operation-id` values.
The provisioner rebuilds the worker's management target from its original RAES provision input.
It runs only the SDK verbs at the fixed trial-control path.
`run` starts the trial with `systemd-run` only when `status` reports `prepared`.
It stops the trial when the deadline and a 900-second drain have passed.
The archive returns through a bounded copy, digest verification, and a create-only object under `trial-exports/`.

## Archive intake

Intake accepts the LilRAE trial seal (`lilrae-trial-record/v1`).
The trial record's run, attempt and trial SDL digest must equal the expected identity.
The SDL digest is the digest of the retained entry's staged trial SDL.
Evidence that names another attempt is refused.
Intake still validates every inventory member and checksum.
A trial seal has no RAES plan, so its plan metadata is empty.

## Cleanup receipt

After verified VM absence, the coordinator records a RAES cleanup receipt.
Each obligation that the outcome triggers reports success, with the worker absence as evidence.
The clean-state claim is `fresh-range-required`.

## Dependency tuple

The tuple is Python 3.14, Django 6.0, RAES 11.0.1, raes-env-packs 7.2.3, and adapter SDK 0.3.0.
