# RAES coordinator for experiment dispatch (#2914)

Today BigRAE compiles the plan, starts one worker for each entry, and collects an archive that the worker seals.
RAES does not own those trials.
So RAES does not make the run records, the attempt decisions, or the replacement decisions.
This design makes BigRAE the RAES coordinator, as the RAES guide "Execute assigned trials" describes.
RAES then owns the trial lifecycle, the decisions, and the records.
BigRAE owns placement: workers, transport, and verified worker destruction.

## Components

| Component | Owner | Responsibility |
| --- | --- | --- |
| Coordinator runtime | `shared.raes.experiment_coordinator` | Builds one RAES `RuntimeControlPlane` on the PostgreSQL control-plane store, admits the retained inputs, and assigns, ingests and advances entries |
| Coordinator target | Same module | Backend components that refuse every native call, because the coordinator never runs a trial |
| Outcome verifier | `shared.raes.assigned_trial_archive` | Validates the sealed archive and verifies each outcome evidence record's run and bytes |
| Dispatch | CMS `_experiment_dispatch` | Claims entries, creates workers, stages each assignment, collects each outcome, retires workers |
| Worker transport | Adapter SDK `trial.py`, provisioner `worker_trial_ops` | Unchanged verbs; new staged files for an assigned trial |
| Apparatus | External distribution | Binds the assignment with `bind_assigned_trial`, runs it to an outcome, and exports the outcome with its evidence |

## Flow

1. Admission retains the inputs as today, then calls `admit_experiment`.
   The experiment identity is the plan identity.
2. Dispatch claims an entry and creates its worker.
3. Dispatch calls `assign_trial(experiment, entry, owner_id=<worker id>, grant=...)`.
   The grant's effective parallelism is the batch concurrency.
4. Dispatch stages `assignment.json` and `inputs.json` (the original `TrialRealizationInputs` carriers) on the worker.
5. The apparatus binds the assignment, advances it until it is complete, and exports `outcome.json` with its evidence in one archive.
6. Dispatch reads the outcome and calls `ingest_trial_outcome`.
   RAES calls BigRAE's outcome verifier. RAES refuses an outcome that the verifier does not confirm.
7. Dispatch calls `advance_trial`. RAES decides retry, replacement, or terminal state.
8. Dispatch retires the worker and verifies that the VM is absent.
9. The batch export calls `experiment_records`.
   BigRAE adds one evidence artifact for each run: the worker identifier, its qualification fingerprints, and the verified absence.

Every dispatch pass builds the control plane again from the same store and admits the retained inputs again.
The RAES ledger in the store keeps attempts, owners, and decisions across passes.

## Verification limits

BigRAE's outcome verifier checks that each evidence record of an outcome belongs to the run and that every byte it references is in the sealed archive with its checksum and size.
RAES ingestion checks the outcome against the retained assignment, its commitments, and its result and cleanup joins.
BigRAE reads the archive; it cannot observe the worker guest. In-guest facts rest on the worker runtime's records.
The adapter that produced an outcome does not verify it.

## Admission

The coordinator realizes every entry when it admits the experiment.
Admission therefore refuses a batch whose entries the backend cannot realize, which the trial compiler alone does not check.

## Cleanup and placement

The execution authority's cleanup plan covers the trial resources inside the worker.
The apparatus runs those obligations on the worker, and the outcome carries their facts.
Worker creation and destruction are placement. RAES leaves placement to the host.
BigRAE records each worker's fingerprints and verified absence as run evidence.
Each trial gets a new worker, so no trial starts on a used VM.

## Compatibility

A batch whose apparatus declares the new `trial.assigned` capability uses this path.
A batch whose apparatus declares only `trial.control` keeps the current path until its apparatus serves assigned trials.

## Threats and controls

| Threat | Control |
| --- | --- |
| A worker claims a result that did not happen | RAES ingestion and the apparatus verifier read the original evidence |
| A worker runs another entry or attempt | RAES binds the assignment to its owner, attempt, plan, and commitments |
| A worker claims its own clean destruction | BigRAE verifies VM absence through the provider |
| Two trials share a VM | Each assignment gets a new worker with independent qualification fingerprints |
| A pass runs twice | The RAES ledger and the worker trial fence refuse a second assignment or start |
