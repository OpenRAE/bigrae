# Run an admitted experiment batch

Dispatch runs each trial of an [admitted batch](admit-pack-experiments.md) on its own disposable worker VM.
An installed apparatus adapter runs the trial on the worker.
BigRAE collects the sealed run and then retires the worker.

Run the commands in an operator-prepared application environment.
Use the installed revision and approved credential files.

## Prepare the deployment

1. Install the apparatus adapter as worker software.
   Its plugin must declare `bigrae.runtime-plugin/v2` and the `trial.control` capability.
   It installs only the trial-control command on each worker.
2. Admit the batch. The requested concurrency sets how many trials run at the same time.
   It cannot exceed the plan's parallel limit, which the scenario's `trial_parallelism` sets.
3. Publish a [worker policy](disposable-workers.md) whose host profile pins the pre-built trial runtime image and selects that installation.
4. Reserve worker capacity for the batch concurrency.
5. Apply the deployment infrastructure. The provisioner needs create-only access to `trial-exports/` in the assets bucket.

Workers use the deployment's keyless model identity (ADR-064).
No model key goes to a worker.

## Run the batch

Each command takes a native credential file, the organization, and the batch.
`start`, `collect` and `reconcile` also take the worker scope.

```bash
uv run python manage.py experiment_dispatch start \
  --credential-file /run/operator/credential \
  --organization 11111111-1111-4111-8111-111111111111 \
  --batch 22222222-2222-4222-8222-222222222222 \
  --scope-kind organization --scope-id 11111111-1111-4111-8111-111111111111
```

| Operation | Effect |
| --- | --- |
| `start` | Claims pending entries up to the concurrency, creates their workers, then reconciles |
| `reconcile` | Advances each claimed entry by one step |
| `collect` | Advances collection and cleanup only; starts no trial |
| `stop` | Requests a stop for each running trial |
| `show` | Prints each entry's state; changes nothing |

Each command prints one JSON line per entry, with the action it took.
Run `reconcile` every few minutes until every entry reports `cleanup-recorded`.
Run it soon after workers become ready: qualification needs a fresh host observation.
A restart loses nothing: each run reads the stored state.

## Entry steps

1. The worker provisions and qualifies (`waiting-for-worker`).
2. BigRAE places an evidence hold, stages the trial inputs, and starts the trial (`trial-started`).
3. The trial runs until it exits or reaches its deadline (`running`).
4. BigRAE validates and stores the sealed run (`collected`).
5. BigRAE releases its hold and retires the worker (`retiring`).
6. After verified VM absence, BigRAE records cleanup and frees the batch slot (`cleanup-recorded`).

## Failures

A failed collection keeps the worker and its hold. The entry stays not collected.
Fix the cause, then run `collect` or `reconcile`.
A failed worker operation leads to `collect-requested`; collection never starts a trial again.

An overdue run leads to `recovery-requested`: BigRAE stops it and collects what it sealed.
`not-sealed` and `start-failed` need operator review; the worker and its hold stay.
`stop` persists a batch stop. No new entry is claimed or started after it.
A failed teardown keeps the slot occupied until the VM is verified absent.
BigRAE does not redispatch an entry automatically.

See the [technical contract](../technical/shifter_platform/experiment-dispatch.md).
