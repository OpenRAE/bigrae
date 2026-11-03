# Admit a pack experiment

Admission retains an installed pack's trial plan and exact scientific inputs.
It creates no VM and makes no model call.
Remote dispatch is a separate operation.

## Prepare the inputs

1. Install the pack for the owning organization through the existing pack installation service.
2. Configure an approved trial archive destination and retention through `trial_archive configure`.
3. Obtain a native bearer credential with installation and organization `manage_content` authority.
4. Save the credential in an owner-only file with mode `0600`.
5. Obtain approved backend, processor, participant, realization-envelope, and execution-authority documents from their owners.

The apparatus authority document contains `schema_version`, `backend`, `processor`, `participants`, `realization_envelope`, and `execution_authority`.
Its schema version is `bigrae.experiment-admission-authority/v1`.
Each participant contains `participant_address` and its owner-supplied `manifest`.
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

Requested concurrency must fit both the approved ceiling and the sealed plan's isolation ceiling.
Current RAES compiler output has a serial ceiling.
A configured ceiling of 200 grants no cloud capacity or provider quota.
A future dispatcher must obtain current capacity before starting a worker.

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
