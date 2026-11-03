# Operate disposable VM workers

Disposable workers provide isolated VM hosts through the Engine range lifecycle.
Each host has one Docker daemon and serves at most one trial.
The service does not dispatch trials or collect their evidence.

## Prepare the deployment

Use an approved GCP deployment with the GCE range backend.
Other worker backends are unsupported.
Use the existing GCP deployment procedure before live operation.
Do not change another tenant or reuse its resources for this smoke.

An installation administrator publishes the worker policy.
The policy contains an outer host plan, an exact GCE image profile, image provenance, Docker version, capacity demand, and global limits.
Use the serialized host plan from the existing RAES planner.
Leave the image profile's machine type empty.
The existing provisioner derives an E2 custom machine type from the plan's CPU and memory.
Use an even CPU count from 2 through 32 and memory aligned to 256 MiB.
Memory must be between 512 MiB and 8 GiB per CPU.
Keep this apparatus plan separate from the experiment SDL.
Use a host image with independent machine and Docker identities on first boot.
No participant container or experiment runtime is required.

Reserve the capacity scope through the existing Engine capacity assessment service.
The scope is an opaque UUID; it does not require a CTF event.
Use enforcing reservations whose per-worker amounts cover the selected VM resources.
Worker admission refuses missing, expired, advisory, and insufficient budgets.
Retained worker draws keep their reservations effective until provider absence.

The [technical contract](../technical/shifter_platform/disposable-workers.md) describes each policy boundary and service entry point.
Policy files contain no credentials.
The policy accepts one approved host profile for new workers.
Existing workers retain their admitted profile after policy changes.

Authenticate commands with an issued bearer credential in an owner-only `0600` file.
Do not pass proof in command arguments.
The credential requires the applicable native authorization actions and its original permission ceiling.
Publishing policy and operator recovery require `installation.manage_cloud_authority`.
Worker creation requires parent launch authority.
Inspect, management access, and retirement require the corresponding range actions.

```bash
python manage.py disposable_workers configure \
  --credential-file /path/to/private-proof \
  --policy-file /path/to/approved-worker-policy.json
```

## Run the synthetic smoke

The smoke starts two workers through bounded parallel admission.
It checks private management access and independent VM, machine, and Docker daemon identities.
It then requests retirement and waits for verified provider absence.
The command prints its owned worker UUIDs before creation.
It preserves those records if creation, qualification, cancellation, or cleanup fails.
An uncertain authorization publication prevents VM dispatch and retains the admitted worker.
An identical create request can retry the original provider binding.
An installation administrator can recover cleanup with the printed identity.

```bash
python manage.py disposable_workers smoke \
  --credential-file /path/to/private-proof \
  --scope-kind organization --scope-id <organization-uuid> \
  --timeout 900
```

Success requires `independent_workers: 2` and `cleanup_verified: true`.
A timeout or failed probe is a failed smoke.
Use the printed UUIDs to inspect retained recovery state.
Do not delete resources by a guessed name or release capacity manually.

## Retain evidence and recover cleanup

Acquire an evidence hold after a worker is ready.
A hold acquired during provisioning cannot guarantee preservation and is refused.
Each caller owns its hold.
Every active hold prevents native destructive admission and dispatch.
An overdue hold requires operator review; it does not authorize deletion.

```bash
python manage.py disposable_workers hold \
  --credential-file /path/to/private-proof --worker-id <worker-uuid> \
  --reason evidence
python manage.py disposable_workers inspect \
  --credential-file /path/to/private-proof --worker-id <worker-uuid>
```

Release your exact hold after evidence collection.
An installation administrator can release another caller's exact hold with `--operator-override`.
The service audits both release paths.

```bash
python manage.py disposable_workers release \
  --credential-file /path/to/private-proof --hold-id <hold-uuid>
python manage.py disposable_workers retire \
  --credential-file /path/to/private-proof --worker-id <worker-uuid>
```

The scheduled range reconciler processes due workers.
Retries use bounded backoff and an attempt limit.
Exhausted cleanup keeps the owner, capacity, profile, and operation evidence.
After investigation and explicit hold release, an installation administrator can resume cleanup.

```bash
python manage.py disposable_workers recover \
  --credential-file /path/to/private-proof --worker-id <worker-uuid>
```

Inspection reports the recovery reason, attempt count, and next review time.
A destroyed status alone does not release capacity.
Only accepted provider absence for the exact native generation settles the worker.
