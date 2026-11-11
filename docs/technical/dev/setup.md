# Developer environment setup

This page deploys a development environment from your own fork of the
repository with GitHub Actions.
The selectable deployment target is `aws-dev`.
The GCP CI adapter is retained, but no GCP environment is selectable.
Contributor deployment needs GitHub secrets, variables, and protected Environments.

To install BigRAE from a published release, use
[Install on Google Cloud](../../getting-started/install-gcp.md). That install needs no
GitHub access.

## Before You Start

Work through this checklist before running any command below. A fresh tenant
standup fails partway if an item is missing, so confirm all of them first.

### Local tooling

- Python 3.12+
- `uv`
- Terraform 1.7+
- GitHub CLI (`gh`) authenticated
- Docker
- **AWS**: AWS CLI v2 configured with SSO or IAM credentials
- **GCP**: `gcloud` CLI authenticated with appropriate project. A GCP deployment
  without GitHub runs the commands from the release's deployer image, which holds
  the other tools. Docker, `oras`, and `cosign` get and verify that image. See
  the [GitHub-less GCP deployment guide](../handbook/gcp-github-less-deployment.md).

### Accounts and access

- A cloud account (AWS or GCP) with billing enabled and permissions to create
  IAM, networking, compute, database, and storage resources.
- Admin access to the GitHub repository to set Actions secrets and variables
  (Settings, then Secrets and variables, then Actions). A GCP deployment without
  GitHub does not need it.
- A domain you control, plus access to its DNS provider. It is required for
  certificate validation (ACM on AWS, managed TLS on GCP) and to point the
  hostname at the load balancer.

### Must already exist before the first Terraform apply (AWS)

These are hard preconditions; the Portal stack plan fails without them. See
[`aws-terraform-apply-order.md`](../../dev/aws-terraform-apply-order.md)
for the authoritative order.

- **Bootstrap has run** for the environment (`scripts/bootstrap/deploy.py
  bootstrap`), creating the S3 state bucket, GitHub OIDC provider, and deploy
  IAM role. This doc walks through it under [AWS Deployment](#aws-deployment).
- **Self-hosted runners provisioned and registered**, if deploying through CI
  (all AWS deploy jobs use `runs-on: self-hosted`). See
  [`aws-runner-provisioning-runbook.md`](../../dev/aws-runner-provisioning-runbook.md).
- **Range AMIs built and the `/shifter/ami/{kali,ubuntu,windows,dc}` SSM
  parameters seeded.** The Portal stack reads these as data sources. See
  [`aws-ami-seeding-runbook.md`](../../dev/aws-ami-seeding-runbook.md).
- **Engine provisioner image built** (CI `_shifter-engine.yml`) so the Portal
  stack can resolve its image digest.

### Must already exist before deploy (GCP)

A release-driven GCP installation needs only the
[installation prerequisites](../../getting-started/install-gcp.md#before-you-start).
The retained GCP CI adapter prerequisites are in
[Retained GCP CI deploy adapter](../../dev/gcp-ci-adapter.md).

### Configuration values

- The single authoritative checklist of every secret and repository variable a
  fresh environment needs, and how each is populated, is in
  [`deploy-secrets.md`](../../dev/deploy-secrets.md). The deploy
  preflight enforces these.

## Root Installation Config

Scaffold, edit, then validate `bigrae.yaml` before deployment. `init` copies the
checked example for your backend to `./bigrae.yaml` (local-only: it writes no
secrets and calls no cloud API):

```bash
# Scaffold ./bigrae.yaml (run `init` with no --backend to list the available backends).
uv run --project shifter/installation bigrae-config init --backend aws

# Edit bigrae.yaml for your deployment, then validate its shape.
uv run --project shifter/installation bigrae-config validate bigrae.yaml
```

Use `--backend gcp` for GCP. See [Installation Config](installation-config.md) for the
field reference.

## Doctor

Once `bigrae.yaml` is filled in, run `doctor` to validate the *selected backend* (in addition to the config shape) before applying infrastructure. It runs the checks the backend
bundle declares (required tools on PATH, secret references, generated outputs, owned
repository paths, and the bundle's credential-free validation checks) and labels each
check as local-only, cloud-read-only, or deployment-mutating. It is non-mutating by default and reports the selected backend/profile. Its output identifies failed readiness checks directly.

```bash
# Local-only checks (default): config, tools, secret references, non-mutating validation.
uv run --project shifter/installation bigrae-config doctor bigrae.yaml

# Additionally run read-only health probes of the deployment endpoint (post-deploy).
uv run --project shifter/installation bigrae-config doctor bigrae.yaml --checks cloud
```

`doctor` exits `1` when any blocking check fails. It is a pre-mutation readiness signal;
the deploy preflight below, Terraform, and runtime health gates remain authoritative for
their own layers.

## Preflight

The deploy preflight is the shared, fail-safe check that every prerequisite is in
place before any change is made. Local and CI entrypoints reuse the prerequisite checks. Missing secrets, tools, or configuration produce one report before Terraform apply.

Run it on demand before deploying:

```bash
# Validate an AWS environment (add --component core|range|portal to scope overlays)
./scripts/bootstrap/deploy.py preflight --cloud aws --env dev

# Validate a GCP deployment input bundle (or pass --inputs <dir>)
./scripts/bootstrap/deploy.py preflight --cloud gcp --env <environment> --store gs://<deployment-config-bucket>
```

The `bootstrap`, `terraform`, and `full` commands run the preflight automatically
at the start. It is interactive by default: it prints the results and asks you to
confirm the manual prerequisites it cannot verify (cloud authentication, DNS
access). Pass `--headless` (or run without a TTY, as CI does) to skip the prompts
and fail on any missing required prerequisite instead.

In CI, the first Identity Platform operator credentials
(`GCP_BOOTSTRAP_ADMIN_EMAIL` / `GCP_BOOTSTRAP_ADMIN_PASSWORD`) are required. To
deliberately skip operator creation, set the `SHIFTER_SKIP_OPERATOR_BOOTSTRAP`
repository variable to `true`; the skip is logged, never silent. A GCP
deployment without GitHub declares the operator in
`settings.operator_bootstrap`; set `enabled: false` to skip it.

## Environments and Terraform Layout

GCP uses one execution root, `platform/terraform/gcp/environments/platform/`.
Deployment input bundles supply GCP values; no tenant values directories remain in this tree.
AWS retains separate `dev` and `prod` Core, Range, Portal and EKS roots.
The AWS production roots are owned by @Brad-Edwards and remain available through
the bootstrap `terraform` and `full` commands and the EKS lifecycle.

### Terraform directories

```text
platform/terraform/
  environments/<env>/             AWS Core stack
    range/                         AWS Range stack
    portal/                        AWS services and data plane
    eks/                           AWS Kubernetes control plane
  gcp/environments/platform/      Shared GCP execution root
  global/                         AWS account-wide infrastructure
  modules/                        Reusable AWS modules
  gcp/global/                     Independent GCP foundation and runner roots
  gcp/modules/                    Reusable GCP modules
```

### Deployment selection

Deployments use an explicit `workflow_dispatch` environment choice. Pushes and pull requests run validation only. The only choice is `aws-dev`.

No GitHub-deployed GCP environment exists; GCP
deployments install from a release. Issue #2672 decides whether the GitHub GCP
deploy path stays. Branch names do not select an environment.

AWS production remains a local operator path; it is not a deploy workflow choice. See [CI/CD](../platform_infrastructure/cicd.md) for the trigger matrix.

### Adding a GCP environment

A GCP deployment without GitHub needs no change to this repository. Apply its
foundation, publish its deployment input bundle, and deploy a release
([GitHub-less GCP deployment guide](../handbook/gcp-github-less-deployment.md)).

A future GCP CI deployment needs reviewed repository changes. See
[Retained GCP CI deploy adapter](../../dev/gcp-ci-adapter.md).

## AWS Deployment

AWS platform workloads run on EKS through the shared Helm chart.
Prepare Core, Range and Portal infrastructure using the
[AWS apply order](../../dev/aws-terraform-apply-order.md).
The Portal root owns persistent AWS services; it does not deploy the application containers.

The maintained application entrypoint uses a validated installation config and attested image digests:

```bash
./scripts/bootstrap/deploy.py eks-deploy \
  --config bigrae.yaml --images .shifter/images.json --profile <aws-profile>
```

Follow the [AWS EKS bundle](../platform_infrastructure/aws-eks-bundle.md)
and [EKS operations](../../ops/portal-eks-operations.md) for prerequisites, protected inputs,
workload identities, ingress, deployment checks and teardown.
Terraform owns cloud infrastructure. Helm owns namespaced platform workloads.
Legacy EC2 portal deployment scripts are not supported entrypoints.

The retained infrastructure-only CLI remains available for `dev` and `prod`:

```bash
./scripts/bootstrap/deploy.py bootstrap --env dev --profile <aws-profile>
./scripts/bootstrap/deploy.py terraform --env dev --profile <aws-profile>
```

Bootstrap renders private backend files in the operator instance directory.
Pass those files to Terraform init; do not edit committed backend examples.
Configure the exact deployment values described in [deploy secrets](../../dev/deploy-secrets.md).

### AWS environment operations

| Doc | Read this when |
|---|---|
| [Deploy secrets and variables](../../dev/deploy-secrets.md) | You configure the GitHub secrets and repository variables of an AWS environment. |
| [AWS Terraform apply order](../../dev/aws-terraform-apply-order.md) | You need the order of the AWS stacks and the preconditions of each one. |
| [AWS AMI seeding](../../dev/aws-ami-seeding-runbook.md) | You seed the range guest AMIs that the portal stack reads. |
| [AWS runner provisioning](../../dev/aws-runner-provisioning-runbook.md) | You provision and register the self-hosted CI runners. |
| [GitHub runner health alerts](../../ops/github-runner-health-alerts.md) | A runner-health alert fired. |
| [Portal on EKS operations](../../ops/portal-eks-operations.md) | You monitor, scale, deploy, troubleshoot, or roll back the portal on EKS. |
| [AWS native identity](../../ops/aws-native-identity.md) | You enable the AWS policy service, admit an AWS service principal, open operator access, or rotate the datastore. |
| [Secrets rotation](../../dev/secrets-rotation-runbook.md) | You rotate deployment or runtime secrets. |
| [Service Discovery ForceNew](../../dev/service-discovery-forcenew.md) | You hit a Service Discovery replacement. |
| [Disaster recovery](../../ops/disaster-recovery.md) | You recover the AWS portal stack after a failure. |
| [AWS environment teardown](../../dev/aws-teardown-runbook.md) | You tear down an AWS environment. |

## Existing Environment Setup

If deploying to an account with existing infrastructure:

### Initialize Terraform

```bash
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform init
```

### Verify State

```bash
AWS_PROFILE=<your-profile> terraform plan
```

A no-change plan shows agreement within the provider reads and inputs that Terraform checked.
It does not prove application readiness, range containment, or recovery.

## Common Issues

Use the [runbook operating contract](../../runbooks/index.md#shared-operating-contract) for recovery authority and evidence handling.
A state lock can belong to an active process.
Confirm its owner has stopped before unlocking.
Preserve state and private inputs before changing local metadata.

### State Lock Error

Someone else is running Terraform, or a previous run crashed:

```bash
# Check who has the lock, then force unlock if needed
terraform force-unlock <LOCK_ID>
```

### Provider Cache Issues

```bash
rm -rf .terraform
terraform init
```

### ACM Validation Timeout

If Terraform times out waiting for ACM:

```bash
# 1. Get the validation records again
terraform output -json acm_validation_records

# 2. Check if DNS is propagated (replace with your actual record name)
dig CNAME _abc123.shifter.yourdomain.com

# 3. If DNS is correct, rerun the reviewed apply
terraform apply
```

Common issues:
- **Trailing dot**: Some DNS providers need the trailing `.` removed from the value
- **Wrong record type**: Must be CNAME, not TXT
- **Propagation delay**: Wait 5-10 minutes after adding records

### Container Pull Failures

Check ECR repo exists and has images:

```bash
aws ecr describe-images --repository-name shifter-prod-portal
```

If empty, push a container first.

## GCP Deployment

GCP provisions with Terraform (`platform/terraform/gcp/`, rooted at
`environments/platform`, whose main module is `modules/platform-core/`). The
Helm chart `platform/charts/shifter/` is the only Kubernetes renderer. The
`deploy.py gcp-deploy` command runs the first install and every update
(ADR-070).

| Task | Page |
| --- | --- |
| Install, update, or remove a deployment from a release | [Install on Google Cloud](../../getting-started/install-gcp.md) |
| Commands, inputs, deploy stages, and retained resources | [GCP deployment handbook](../handbook/gcp-github-less-deployment.md) |
| Failures | [RB023](../../runbooks/rb023-gcp-deployment.md) |
| Releases, checkout deploys, and test deploys | [Contributor GCP releases and test deploys](../../dev/gcp-contributor-deploy.md) |
| The retained GitHub CI adapter (`_gcp-dev.yml`) | [Retained GCP CI deploy adapter](../../dev/gcp-ci-adapter.md) |
| Participant OpenVPN access | [Participant OpenVPN access](../../dev/gcp-range-cell-deploy.md#participant-openvpn-access) |
