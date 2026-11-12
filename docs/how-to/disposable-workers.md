# Qualify disposable VM workers

Disposable workers provide fresh VM hosts through the existing Engine lifecycle.
Each VM has one Docker daemon and can serve at most one trial.
The service supplies ownership, capacity, evidence holds, and tracked cleanup.
It does not run trials or collect their evidence.

## Prepare the deployment

Use the approved [GCP deployment procedure](../technical/handbook/gcp-github-less-deployment.md).
The deployment must select the GCE range backend and contain the qualification command.
The recorded bootstrap administrator must remain active, have personal-token eligibility, and have the required application permissions and customer membership.
Cloud access permits server execution; it does not grant application permissions.

Prepare private bootstrap facts using the existing deployment procedure.
The facts select the exact provider issuer and subject recorded at identity activation.
The command refuses another identity or a changed authorization-provider binding.
Copy the facts to a regular file owned by the application process with mode `0600`.
Projected Secret symlinks must first be copied to that private file.

Publish an approved worker policy through `configure_worker_policy` or supply it with `--policy-file`.
The policy file also requires owner-only mode `0600`.
The policy names each host profile under `profiles`. Qualification uses `default` unless `--profile` names another.
For each profile, pin one Linux host plan, an exact GCE image name and numeric image ID, its provenance digest, Docker version, and resources.
Use the existing image preparation and publication procedure for those facts.
The host plan is apparatus configuration, separate from experiment SDL.
No participant container or experiment runtime is required.

The existing Ubuntu range image can supply Docker and the standard host bootstrap.
Use a publication that clears machine and Docker identities before capture.
Older publications need a rebuild through the protected guest-image workflow.
See [Linux identity at capture](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/gcp-guest-images.md#linux-identity-at-capture).

To use an ARM64 worker, set the image profile `machine_type` to a predefined C4A type with the plan's vCPU count.
Set `disk_type` to `hyperdisk-balanced`, `nic_type` to `GVNIC`, and `disk_interface` to `NVME`.
Set `enable_secure_boot` to `false` only when the trial loads an unsigned kernel module.
The image must be an ARM64 image.

Reserve capacity through the existing Engine assessment service and deployment catalog.
The profile names that reservation scope and its approved capacity partition.
The partition must match the deployment project, region, and GCE backend.
Use enforcing reservations with per-worker costs that cover the pinned VM.
Missing, expired, advisory, insufficient, or wrong-partition budgets refuse admission.
Never insert reservation rows by hand for a live smoke.

Every GCP deployment declares the `gce-workers` partition for its project and range region.
Its `vcpu` and `instances` budgets are enforcing database reservations.
Each worker draws one instance and `range_cells.worker_vcpu` vCPUs, 8 by default.

## Run qualification

Execute inside the approved application runtime through the existing operator cluster access:

```bash
python manage.py qualify_disposable_workers \
  --bootstrap-facts /path/to/private-bootstrap.json \
  --scope-kind organization --scope-id <approved-organization-uuid> \
  --timeout 900
```

The command acts as the existing recorded administrator.
It creates no user, service account, membership, or policy grant.
It issues native Knox credentials with fixed actions and separate exact targets for configuration, launch, and each worker.
Proof stays in the process and is revoked on every handled exit.
A 35-minute expiry bounds credentials abandoned by process death.
The catalog initializer's credential remains unchanged.

The command prints its worker UUIDs before creation.
It starts two workers in parallel, checks private SSH access, and verifies distinct VM, machine, and Docker daemon identities.
It also verifies that each realized VM has the machine type, Secure Boot state, interfaces, and image of the profile.

It then requests retirement through Engine and waits for verified provider absence.
Success requires `independent_workers: 2` and `cleanup_verified: true`.
A failed probe, timeout, uncertain cleanup, or failed credential revocation fails the smoke.
Local synthetic tests do not replace this live qualification.

## Recover retained workers

Keep the printed worker IDs if qualification fails.
Native custody, reservations, and cleanup obligations remain after credential expiry.
Use the same recorded operator and exact customer scope for bounded recovery:

```bash
python manage.py qualify_disposable_workers \
  --bootstrap-facts /path/to/private-bootstrap.json \
  --scope-kind organization --scope-id <approved-organization-uuid> \
  --recover <worker-uuid>
```

Recovery accepts at most two exact workers and preserves their admitted apparatus.
It does not release evidence holds.
Hold owners or an authorized operator must release each exact hold through the existing worker service before cleanup can continue.
Do not delete resources by guessed names or release capacity manually.
The [technical contract](../technical/shifter_platform/disposable-workers.md) describes the service boundaries and retention rules.
