# Experiment admission service contract

The public `cms.services` facade owns organization admission and operational persistence.
The `shared.raes.experiment_admission` module wraps the released experiment APIs.
It does not define a scientific schema or enumerate factors.
ADR-027 continues to exclude the retired `cms.experiments` application.

## Operations

All operations take a native `CredentialContext` and an organization UUID.
Admission also requires installation `manage_content` authority for the supplied apparatus documents.
Other writes require organization `manage_content` authority.
Scientific-input reads and token-based observations require organization `read_content` authority.
Claim recovery requires organization `manage_content` authority because it returns an operational token.
Every write checks local credential state and SQL ancestry inside its transaction.

| Operation | Inputs | Result |
| --- | --- | --- |
| `admit_experiment_batch` | Registered scenario, experiment selector, apparatus authority, requested concurrency | Immutable retained batch |
| `load_experiment_batch` | Batch UUID | Exact retained inputs and metadata |
| `claim_experiment_entry` | Batch UUID and preallocated entry identity | Exclusive claim or no pending claim |
| `recover_experiment_claim` | Batch UUID and preallocated entry identity | Existing attempt for reconciliation, or no claim yet |
| `record_experiment_worker` | Claim token and opaque worker reference | Bound worker identity |
| `observe_experiment_attempt` | Claim token and fixed operational disposition | Current operational projection |
| `record_experiment_collection` | Claim token and committed archive receipt UUID | Verified collection reference |
| `record_experiment_cleanup` | Claim token and verified owner cleanup receipt | Released claim capacity after terminal observation |

A claim token is also the execution attempt identity.
It does not replace authorization.
The entry's run identity comes from the retained RAES plan.
Scheduling order cannot allocate another run or change a trial's scientific inputs.
One initial attempt is supported per entry.
If a claim response is lost, an operator with organization `manage_content` authority can recover the same token by batch and entry.
Recovery does not allocate another attempt, release capacity, or authorize redispatch.
Reconcile the existing worker and verify cleanup before releasing capacity; claims never expire into automatic redispatch.

[Experiment dispatch](experiment-dispatch.md) validates worker capacity, isolation, and cleanup before resource use.
The batch lock enforces requested concurrency for active claims.
An observed terminal disposition remains active until an authorized caller records verified cleanup.
The released RAES validator checks the cleanup receipt against the retained plan and exact attempt identity.
Only successful cleanup releases capacity.
The caller must verify the owner's actual cleanup evidence before submitting its receipt.
Collection records archive custody only and does not release dispatch capacity.
This conservative rule prevents evidence collection from authorizing overlapping resources.

For collection, call `intake_trial_archive` with the retained plan's experiment, plan, entry, run, and attempt identities.
Then call `record_experiment_collection` with its committed receipt UUID.
The service checks all identities, plan and entry digests, receipt state, expiry, and pinned destination.
Receipt presence does not declare scientific success or resource cleanup.

## Persistence

`ExperimentBatch` stores the complete retained JSON record and its SHA-256 digest.
The record includes original input text, the expanded family, hydrated snapshots, and complete owner documents.
It also includes the RAES plan, normalized participant configurations, capture specifications, and dependency tuple.
Referenced local artifact bytes are verified through the released env-packs resolver and retained as base64.
The released control-context pin helper joins selected configuration and authored SDL assets to their exact descriptors.
Selected content uses absolute `raes-environment-pack:` locators and exact inventory descriptors.
The published artifact resolver verifies the original bytes before retention.
Unavailable or changed selected content prevents admission.
Original documents and referenced artifacts each have a separate 16 MiB aggregate bound.
Destination and resource limits are pinned at admission.
Database triggers forbid changes to batch inputs and entry identities.
Tenant plan identity and entry/run uniqueness constraints prevent ambiguous reloads.
Operational changes cannot replace scientific inputs.
Immutable service projections live in the private `_experiment_batch_records` module; callers use the public `cms.services` facade.

Reload verifies the retained digest and the released sealed-plan validator.
It returns a fresh in-memory projection, so caller mutation cannot change the stored record.
It does not require the original pack to remain installed.
Admission failure commits no partial batch or entry set.
Audit records contain opaque batch identifiers and fixed dispositions.
Public errors contain no authoring input, provider payload, or parser details.

## Dependency tuple

The executable tuple is Python 3.14, Django 6.0, RAES 11.0.0, and raes-env-packs 7.2.4.
Reload refuses an unsupported RAES/env-packs tuple.
Portable plan and configuration versions remain subject to their owner validators.
Current compiler limits are 10000 coordinates, domain values, and product outputs, plus a 32 MiB sealed plan.
The complete retained record has a separate 64 MiB bound.
There is no silent study reduction or consumer-owned partitioning.
The released typed factorial profile accepts fixed nuisance selections and seeded allocation.
Unsupported sampling combinations fail through the owner validator.
Local pack staging uses the existing package byte and member bounds.
Their defaults are 1 GiB expanded bytes and 20000 members.
Provision temporary disk for one expanded pack and, for object-backed packs, its bounded compressed archive.

The synthetic installed-package fixture comes from the MIT-licensed env-packs 7.2.2 source distribution.
Its license remains beside the fixture.
Tests use published manifests and no private pack content.

See the [architecture](../../architecture/experiment-admission-design-2742.md) and [operator instructions](../../how-to/admit-pack-experiments.md).

## Result organization

The authenticated `experiment_batch export` operation reads retained admission
inputs and the complete operational entry inventory through CMS services.
It does not claim, start, retry or replace an entry. Assignment metadata is
reported separately from observed start times and scientific outcomes.
See [the result export design](../../architecture/experiment-result-exports.md)
for the manifest, CSV/JSON indexes and explicit size limits.

Result indexes retain condition, block, replicate, plan-entry, run-version and
execution-attempt identities. Selected configurations remain admission facts;
execution accounting alone does not prove an observed configuration. Run
realization records and referenced original usage disclosures supply observations
where present. Replacement origins retain their root and parent identities.

Distinct original archive observations remain separate index rows. Counts use
unique execution-attempt identities, so overlapping histories do not add trials.
Usage retains its recorded attempt scope; an unassigned usage disclosure stays
unknown instead of being allocated to an attempt. Current content-read and
content-management authority are checked before publication and each storage effect.

The observed configuration includes recorded realized bindings and selections.
The manifest lists missing attempt archives as well as missing expected entries.
An earlier collected archive cannot satisfy a distinct later claim. Listing a
missing archive does not assert that its claim started or produced an outcome.

Export collection completeness includes unresolved archive versions and transfers,
even when an earlier version of the same attempt was collected. A matching
verified later delivery resolves an interrupted transfer without adding an attempt.

Interrupted transfers and identical-byte successful retries remain separate custody
observations. When the archive becomes unavailable, reconciliation preserves
receipt summaries and every source reference; different custody states alone
do not create a scientific conflict.

The private `_experiment_export_records` module owns deterministic projections
and formatting. `_experiment_exports` composes inventory reads, while
`_trial_archive_exports` publishes through existing custody primitives.
