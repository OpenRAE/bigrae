# GitHub Actions Self-Hosted Runners

Self-hosted runners for GitHub Actions workflows. The AWS fleet uses `self-hosted`. A configured GCP CI tenant uses its own deployment label and runner fleet. See [GCP-native runners](#gcp-native-runners-dev-tenant-containment).

## Scheduling policy

GitHub Actions does not provide native fallback from `ubuntu-latest` to
self-hosted runners or a priority order across those runner classes.
Workflow jobs must choose a concrete scheduling target.

BigRAE splits workflow capacity by job type. Portable quality jobs run
on `ubuntu-latest` to use the GitHub-hosted runner allotment, while
deployment, image build, Packer, and environment-mutating jobs remain on
`self-hosted` custom runners.

## Infrastructure

| Parameter | Value |
|-----------|-------|
| **Terraform** | `platform/terraform/global/github-runner/` |
| **Instance type** | `t3.large` |
| **AMI** | Amazon Linux 2023 (latest) |
| **Count** | Module default: 2; committed `dev.tfvars`: 3 |
| **Region** | `us-east-2` |
| **Access** | SSM Session Manager (no SSH) |

## Provisioning

Instances are created by Terraform with a user_data script that installs dependencies:

- Docker
- Git, jq, tar, unzip
- Python 3.12 + pip + devel headers
- Node.js + npm

The user_data script downloads the GitHub Actions runner binary but does **not** register it. The bootstrap CLI performs registration and verifies each runner online.

## Post-Provision Setup

Use the [AWS runner provisioning procedure](../../dev/aws-runner-provisioning-runbook.md).
It owns installation, registration, network isolation, health checks, removal, and recovery.
Run account bootstrap first to create the shared state backend.
Obtain cloud and repository administration authority before provisioning billable runner instances.

### 1. Register the runner

Run the existing bootstrap command from the repository root:

```bash
./scripts/bootstrap/deploy.py runners --env dev --profile <dev-account-profile>
```

The command applies the runner root, creates one registration token per runner, and registers over SSM.
It verifies the requested fleet online through the GitHub API.
Tokens remain outside Terraform state, user data, secret stores, and logs.
For failure, use the provisioning runbook rather than copying tokens into a command or issue.

### 2. Add the runner service user to the docker group

The existing startup and registration scripts configure the service user.
If Docker access fails, inspect that user's group membership through the approved SSM path.
Follow the provisioning runbook's repair procedure.

### 3. Install and start the service

Bootstrap installs and starts the service during registration.
A running service alone does not prove that GitHub accepts the runner.

### 4. Verify

Require every expected runner to appear online with its intended labels.
Then check its health monitor through the [runner alerts procedure](../../ops/github-runner-health-alerts.md).
Use the provisioning runbook for removal and cleanup; unregistering alone does not stop instance costs.

## Naming

Instances are tagged `shifter-github-runner-{N}` (1-indexed).

## IAM Permissions

The runner role (`shifter-github-runner`) has:

| Policy | Purpose |
|--------|---------|
| `AmazonSSMManagedInstanceCore` | SSM Session Manager access |
| ECR inline policy | Push/pull container images |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `permission denied` on Docker socket | Runner service user not in `docker` group | `sudo usermod -aG docker <user>` + restart service |
| Runner offline in GitHub | Service not started or crashed | `sudo ./svc.sh status`, then `sudo ./svc.sh start` |

## GCP-native runners (dev-tenant containment)

The runner story above is AWS-only. GCP-dev CI historically ran on the same AWS
fleet, so a GCP dev tenant could not stand up without an AWS one. Issue #1546 added GCP-native runners to separate AWS and GCP contributor deployments. Each fleet can operate without the other. This is
the dev-tenant amendment to the runner-isolation rule (ADR-053-R3, carried from
ADR-033-R2).

The runner serves only the GCP deployments that GitHub CI deploys. A GCP
deployment that runs without GitHub needs no runner. An operator runs the
deployer image of a published release (ADR-070, see the
[GitHub-less GCP deployment guide](../handbook/gcp-github-less-deployment.md)).

| Parameter | Value |
|-----------|-------|
| **Terraform root** | `platform/terraform/gcp/global/github-runner/` (dedicated GCS state prefix, separate from the platform root) |
| **Network module** | `platform/terraform/gcp/modules/github-runner-network/` |
| **Instance** | private-only Shielded VM (no external IP), OS Login, dedicated least-privilege service account |
| **Network** | dedicated custom VPC, private subnet with flow logs, Cloud NAT egress, SSH ingress from Google's IAP range (`35.235.240.0/20`) only |
| **Label** | Deployment name (registered with `--no-default-labels`, so it never matches bare `runs-on: self-hosted`) |

### Provisioning + registration

Runners are provisioned and registered by the bootstrap CLI, using the
operator's default gcloud/ADC identity (no service account key):

```bash
./scripts/bootstrap/deploy.py runners --cloud gcp --env <environment> --project-id <gcp-project>
```

The flow applies Terraform and creates a single-use registration token per runner through `gh api`. Tokens remain in memory until delivery over `gcloud compute ssh --tunnel-through-iap` stdin. The host receives a root-only `0600` temporary file.

The token is kept out of the operator's argv/logs, a
Terraform input/output/state value, instance metadata, and Secret Manager. Non-interactive `config.sh` requires `--token`; it has no stdin/file/env input. Its `Console.ReadKey` prompt fails with redirected stdin.

The isolated runner briefly passes `--token "$(cat "$TOKFILE")"` in process arguments. The temporary file is then removed and the single-use token expires. The command fails
closed unless every runner registers cleanly AND the GitHub API reports it online
with the requested deployment label.

The GCE startup script installs a pinned, checksum-verified runner but never
registers it (no token on the host), so registration stays entirely on the
out-of-band IAP path.

### Isolation and scheduling

- Each GCP deployment label keeps its CI off the AWS `self-hosted` pool and
  every other tenant's runner. `_gcp-dev.yml` selects the allowlisted deployment
  input as `runs-on`. No CI-deployed GCP tenant exists after #2668, so no
  deployment label is in use.
- The ADR-003-R5 exposure checker treats the dynamic GCP deployment selector as
  self-hosted-class, so the cut-over jobs keep their pull-request-reachability
  gate (no fork PR can reach a self-hosted runner). New dynamic self-hosted
  selectors must be added to that checker.
- Network isolation is pinned by `check-tf-gcp-runner-network` (ADR-008-R8):
  a dedicated custom VPC (never the default network) with IAP-only SSH.

### Custom actionlint label

Literal custom labels are declared in `.github/actionlint.yaml`. The reusable GCP
workflow selects its label through an expression, which actionlint validates as
an expression rather than a literal runner label.
| ECR auth failures | IAM role missing ECR permissions | Check `aws_iam_role_policy.ecr` in Terraform |
