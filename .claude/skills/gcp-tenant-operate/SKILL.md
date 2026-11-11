---
name: gcp-tenant-operate
description: Install, update, smoke-test, diagnose, and tear down a GitHub-less GCP BigRAE deployment with deploy.py (ADR-070). Use when the user asks to deploy, upgrade, destroy, or debug a GCP tenant.
---

# Operate a GCP tenant

This skill is the agent workflow for one GCP deployment. The procedure and
the facts are in these documents. Read the section that you need; do not work
from memory:

| Need | Document |
| --- | --- |
| Install, complete, update, or remove: the procedure, in order, with prerequisites | [Install on Google Cloud](../../../docs/getting-started/install-gcp.md) |
| Each lifecycle command, its use, and the check after it | [Lifecycle commands](../../../docs/technical/handbook/gcp-github-less-deployment.md#lifecycle-commands) |
| Bundle files, deploy stages, lock, evidence, keys, identity options, and retained resources | [GCP deployment handbook](../../../docs/technical/handbook/gcp-github-less-deployment.md) |
| `bigrae.yaml` settings blocks and their defaults | [Installation config](../../../docs/technical/dev/installation-config.md#supported-backends) |
| Range-cell settings, range egress, and participant OpenVPN | [GCP GCE range-cell deploy runbook](../../../docs/dev/gcp-range-cell-deploy.md) |
| Failure symptoms, investigation commands, and resolution by stage | [RB023](../../../docs/runbooks/rb023-gcp-deployment.md) |
| A checkout deploy without Docker, the release manifest without Docker, hand-patches, and test tooling | [Contributor GCP releases and test deploys](../../../docs/dev/gcp-contributor-deploy.md) |
| Which release or contributor build can install | [Deployment compatibility](../../../docs/technical/platform_infrastructure/deployment-compatibility.md) |
| The design | [GitHub-less GCP deployment design](../../../docs/architecture/github-less-gcp-deployment-design-2571.md) |

Use the `gcp-release` skill to publish the release that you deploy.

## Rules

- Get the tenant inputs from the user: project ID, deployment name, hostname,
  operator email, release revision or deployer digest, and range image
  location. Keep them out of commits, issues, PRs, and docs. The repository is
  public.
- Use a contributor build from `dev` or `deploy-test` only with the user's
  approval for the target deployment.
- For each failure, first check `origin/dev` and the issue tracker for an
  existing fix or issue. Reuse an existing issue. Then fix the cause, add
  tests, and open a PR to `dev`. Close another issue that your fix resolves.
- Never merge into `dev` or `main`, and never close a PR. The user does that.
- Never weaken a gate to pass it: no ignore entries, no skipped scans, no
  bypass flags. Fix the finding.
- Hand-patch a running test cycle only after the fix is in a PR
  ([Hand-patch a checkout deploy during a test cycle](../../../docs/dev/gcp-contributor-deploy.md#hand-patch-a-checkout-deploy-during-a-test-cycle)).
- Do not change the global gcloud account. Pin it per command with
  `CLOUDSDK_CORE_ACCOUNT`. When gcloud reports `Reauthentication failed`, ask
  the user to run `gcloud auth login` and `gcloud auth application-default
  login`.

## Run the commands

1. Verify that the selected release contains the required lifecycle interface.
   Use its deployer image when Docker is available.
2. Without Docker, follow
   [Deploy from a checkout](../../../docs/dev/gcp-contributor-deploy.md#deploy-from-a-checkout)
   and [Read the release manifest without Docker](../../../docs/dev/gcp-contributor-deploy.md#read-the-release-manifest-without-docker).
3. Run a deploy or a destroy in the background with its output in a log file.
   Report the stage lines: `Infrastructure:`, `Rollout:`, `✓`, `✗`, and `⚠`.
   Installation time varies with provider capacity and image availability.
4. Before using `--break-lock`, prove that the holder has stopped.
   Confirm the deployment, lock evidence, and absence of another active operator.
5. Report success only after every check in the lifecycle table for that
   command passes.
