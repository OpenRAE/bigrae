# Admit a pack experiment

Admission retains an installed pack's trial plan and exact scientific inputs.
It creates no VM and makes no model call.
[Dispatch](run-experiment-batches.md) is a separate operation.

Run the commands in an operator-prepared application environment.
Use the installed revision and approved credential files.

## Prepare the inputs

1. Install the pack for the owning organization through the existing pack installation service.
2. Configure an approved trial archive destination and retention through `trial_archive configure`.
3. Obtain a native bearer credential with installation and organization `manage_content` authority.
4. Save the credential in an owner-only file with mode `0600`.
5. Obtain approved backend, processor, participant, realization-envelope, and execution-authority documents from their owners.
6. If a participant manifest names a backend configuration owner, install the adapter that declares that owner.
   Wait until the installation is ready.

The apparatus authority document contains `schema_version`, `backend`, `processor`, `participants`, `realization_envelope`, and `execution_authority`.
Its schema version is `bigrae.experiment-admission-authority/v1`.
Each participant contains `participant_address` and its owner-supplied `manifest`.

The optional `worker_profile` field names the published worker host profile for every trial of the batch. It defaults to `default`.
Admission records that profile's name and digest, and refuses a profile that is not published.

The optional `max_concurrency` field defaults to 200.
Its supported configuration range is 1 through 10000.
Installation authority approves these documents for this admission.
The pack cannot approve apparatus or load executable validators.

Selected prompt assets must include their actual bytes in the installed pack's verified artifact inventory.
Their absolute `raes-environment-pack:` locators and complete descriptors must match that inventory.
Admission refuses missing, changed, or unavailable selected content.

## Admit without dispatch

```bash
uv run python manage.py experiment_batch admit \
  --credential-file /run/operator/credential \
  --organization 11111111-1111-4111-8111-111111111111 \
  --scenario synthetic-family \
  --experiment synthetic-study \
  --apparatus-file /run/operator/apparatus.json \
  --concurrency 1
```

The command prints the batch identity, retained plan identity, expected trial count, and resource limits.
It does not print prompts, scenario bodies, or credentials.
An identical admission returns the same batch and preallocated run identities.
Changed limits or destinations conflict under the same plan identity.
Use the retained batch identity for reload.

```bash
uv run python manage.py experiment_batch show \
  --credential-file /run/operator/credential \
  --organization 11111111-1111-4111-8111-111111111111 \
  --batch 22222222-2222-4222-8222-222222222222
```

Reload requires organization `read_content` authority.
It reads the immutable retained inputs without loading the source pack or allocating new runs.

## Understand the limits

Requested concurrency must fit both the approved ceiling and the sealed plan's admitted parallelism ceiling.
The SDL `trial_parallelism` value sets the admitted parallelism ceiling.
A plan without `trial_parallelism` has a serial ceiling of one.
A configured ceiling of 200 grants no cloud capacity or provider quota.
[Dispatch](run-experiment-batches.md) obtains current worker capacity before it starts a worker.

The released compiler bounds coordinates, domain values, and product outputs at 10000 each.
The plan limit is 32 MiB.
The complete retained record limit is 64 MiB.

Original documents and referenced local artifacts each have a 16 MiB aggregate limit.
The authority document limit is 4 MiB.
Oversized studies fail without partial admission.
The command never partitions or reduces a factorial design.
Owner-supported partitioning needs a later reviewed release.

Keep retained research inputs under the database's access and backup controls.
This feature supplies no automatic scientific-input retention or deletion policy.
Archive retention remains the existing destination policy.

See the [service contract](../technical/shifter_platform/experiment-admission.md) for dispatch and collection operations.

## Export retained results

Use organization `manage_content` authority and the existing approved archive
storage destination. The command works from retained batch inputs and archives.

```bash
uv run python manage.py experiment_batch export \
  --credential-file /run/operator/credential \
  --organization 11111111-1111-4111-8111-111111111111 \
  --batch 22222222-2222-4222-8222-222222222222
```

The command returns storage references to `manifest.json`, `index.json` and
`index.csv`. The manifest lists original source receipts, archive digests and
members, counts, collection completeness, and missing or incomplete data.
Missing archive versions remain visible even when an earlier version of the
same attempt was collected.
The indexes include every expected entry and the known run versions and attempts.

Read collection status, capture completeness and scientific outcome separately.
A failed trial can have a completely collected archive. An assigned worker does
not establish a start or scientific outcome.

Unknown values remain null in JSON
and empty in CSV; nested CSV fields contain JSON. CSV text that can start a
spreadsheet formula is prefixed with an apostrophe. Original archive bytes remain unchanged.

Repeating the command with unchanged inputs produces the same file
content. Repeat it after new archives arrive to update the inventory.

Exports are limited to 10000 expected entries, 10000 experiment archive inventory
observations and 128 MiB of derived output and retained export metadata.
The command refuses unsupported sizes without truncation. Each exported file has
an explicit transfer record and the configured retention expiry. The existing
`trial_archive purge` operation removes expired, settled export objects as well
as expired original archives. Failed publication returns no successful manifest
reference; retain the original archives and retry with current authority.
