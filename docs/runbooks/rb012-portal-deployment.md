# RB012: Portal installation or deployment

Applicability: GitHub-less GCP releases and configured AWS contributor deployments.
Operator: release/platform owner. Verified: 2026-10-23.

Use the [shared operating contract](index.md#shared-operating-contract) before investigation or recovery.

## Symptom

A new installation or upgrade is required, a deployment failed, or the running
portal revision does not match the approved release.

## Investigation

1. Record the intended Git revision, image digests, and approved configuration revision.
   Record the deployment target, Terraform plan/run, and last successful deployment.
   For a contributor deployment, confirm a permitted workflow target.
2. For a source-based contributor deployment, validate `bigrae.yaml` without reading secret values:

   Read-only command:

   ```bash
   uv run --project shifter/installation bigrae-config validate bigrae.yaml
   uv run --project shifter/installation bigrae-config doctor bigrae.yaml
   ```

3. Inspect the latest `Deploy` workflow gates: quality, provider validation,
   Terraform plan/apply, image build/scan, migration, Helm rendering, rollout,
   certificate/readback, and post-deploy smoke.
4. For a GCP deployment without GitHub, read the `gcp-deploy` output and its
   evidence. The scan evidence is under `release-scans/` and the running-image
   evidence is under `deployments/` in the release-evidence bucket. See
   [Evidence](../technical/handbook/gcp-github-less-deployment.md#evidence) in the GitHub-less
   GCP deployment guide. For a failed `gcp-deploy` run, use
   [RB023](rb023-gcp-deployment.md).
5. The current top-level workflow has no generic `prod` choice. A child
   workflow's support for a profile is not authorization to invent a target or
   run local production deployment commands.

## Resolution

For installation, follow [Install on Google Cloud](../getting-started/install-gcp.md).
Use a verified release that contains the deployer image.
Releases through v4.1.1 do not contain that image.

For a configured AWS contributor deployment, dispatch `.github/workflows/deploy.yml` from the approved revision.
Select its permitted `aws-dev` target and protected environment.
Do not retag images or apply local Helm or Terraform for incident recovery.
Verify rollout, running digests, managed certificate, `/health/`, worker heartbeats, and post-deploy smoke.

For a GCP deployment without GitHub, run `gcp-deploy` from the deployer image
of the approved release
([GitHub-less GCP deployment guide](../technical/handbook/gcp-github-less-deployment.md)). Use
`--first-install` until DNS points at the ingress address. To roll back, run
the deployer image of an earlier verified release only when its schema is compatible.
An atomic Helm rollback does not restore database, identity, policy, or infrastructure state.
Use [RB015](rb015-database-migrations.md) before a rollback that affects data.

## Prevention

Retain release evidence, protected-environment approvals, immutable digests,
saved Terraform plans, migration results, and smoke output. Rehearse bootstrap
and rollback against a clean owned environment. See [Install on Google
Cloud](../getting-started/install-gcp.md) and the
[GitHub-less GCP deployment guide](../technical/handbook/gcp-github-less-deployment.md).

Escalate if the target is unavailable, the artifact identity is unknown, or a gate is bypassed. Also escalate rollback that requires a data downgrade.
