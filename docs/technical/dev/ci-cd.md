# CI/CD Pipeline

How GitHub Actions validates and deploys BigRAE.

## Overview

All CI/CD runs through GitHub Actions. The main orchestrator is `deploy.yml`,
which coordinates:

1. **Quality** - Linting, tests, security scanning
2. **Core** - ECR repositories (foundation)
3. **Range** - Range VPC infrastructure
4. **BigRAE Engine** - Container build
5. **BigRAE Platform** - Application infrastructure, containers, deployment

## Trigger Rules

Environment deploys are **manual**: run the Deploy workflow and pick the
`environment` input. Push and pull_request run validation only; no branch name
triggers a deploy (#730).

| Event | What Runs |
|-------|-----------|
| Pull request | Quality only; no deploy |
| Merge group in the `dev` merge queue | `CodeQL`, `Lint PR title`, `GitGuardian scan`, and PR Gate with Quality; no deploy |
| Push to `dev` / `main` | Quality only; no deploy |
| Manual dispatch, `environment: aws-dev` | Quality, then AWS dev deploy |
| Release Please release on `main` | GCP release (`release-gcp.yml`) for the tagged commit; no deploy |
| Manual dispatch of `packer-gcp.yml` on `dev` or `main` | Build, validate, and publish one GCP guest image; no deploy |

No GCP tenant deploys through GitHub Actions after #2668. GCP tenants install
published releases with the GitHub-less commands (ADR-070). The GCP deploy jobs
stay in `deploy.yml`, but no `environment` option selects them; #2672 decides
the future of that path.

Run a deploy from the Actions UI (**Deploy → Run workflow**, pick the branch to
deploy and the `environment`) or the CLI:

```
gh workflow run deploy.yml --ref <branch> -f environment=aws-dev
```

The branch you run it from is the code that deploys; the `environment` input
picks where it goes. `dev` is the integration branch (Quality only).

## Merge Queue

Pull requests to `dev` merge through a GitHub merge queue (ADR-003-R9).
`main` does not use a merge queue and keeps strict status checks.

The `dev` repository ruleset is in `docs/adr/dev-ruleset.json`.
GitHub configures a merge queue only through a ruleset.
The ruleset requires the `Lint PR title`, `PR Gate`, and `GitGuardian scan` contexts and CodeQL code scanning results.
It does not require strict status checks, because the queue tests each pull request against the latest `dev`.
The queue squash-merges (ADR-042-R4) and can put more than one pull request in a merge group.

A pull request must pass the required checks before it enters the queue.
The queue then makes a merge group commit that contains `dev`, the queued pull requests in front, and the pull request.
Each required context runs again on the `merge_group` event for that commit.
When a check fails, the queue removes the pull request, and the pull request does not merge.

On a merge group, the workflows have no pull request payload:

- Quality change detection compares with the queue base branch. The SonarQube Cloud scan uses the same base, so tests and coverage run for all new code in the merge group.
- The other change detection and the diff-based gates compare with `merge_group.base_sha`.
- `Lint PR title` reads the current titles of the queued pull requests in the merge group.
- `GitGuardian scan` runs `ggshield` on the merge group commits. The GitGuardian App does not report on a merge group.
- The SonarQube Cloud scan is a pull request analysis of the queued pull request against the queue base branch.
- CodeQL gates `dev` through a `code_scanning` ruleset rule. The code scanning check run does not report on a merge group, so it cannot be a required status check.

The composite action `.github/actions/merge-group-prs` reads the queued pull requests from the GraphQL merge queue.
The `dev-merge-queue` ADR guard fails when a required producer does not run on `merge_group`.

A repository administrator applies the ruleset:

```bash
gh api -X POST "repos/{owner}/{repo}/rulesets" --input docs/adr/dev-ruleset.json
```

The ruleset replaces the classic branch protection for `dev`.
Remove the classic `dev` protection after the ruleset is active.

## Workflow Files

```
.github/workflows/
├── deploy.yml              # Main orchestrator
├── _quality.yml            # Linting, tests, Checkov
├── _core.yml               # ECR repositories
├── _range.yml              # Range VPC
├── _gcp-dev.yml            # GCP CI wrapper over the gcp-deploy commands
├── _shifter-engine.yml     # Shifter Engine container
├── _shifter-platform.yml   # Shifter Platform infra + deploy
├── packer-gcp.yml          # GCP guest image build, validation call, and publication
├── packer-gcp-validate.yml # GCP guest candidate-boot validation (packer-gcp.yml calls it)
└── release-gcp.yml         # GCP release images and deployer image (release-please.yml calls it)
```

Underscore prefix (`_*.yml`) indicates reusable workflows called by `deploy.yml`.

## Dependency Chain

```
Quality (must pass first)
    │
    ▼
  Core (ECR)
    │
    ├──────────────┐
    ▼              ▼
  Range    Shifter Engine
    │              │
    └──────────────┘
            │
            ▼
  Shifter Platform Plan/Deploy
```

Downstream AWS jobs use explicit `needs.<job>.result` gates. A skipped upstream
is acceptable when its path filter did not select it, but a failed or cancelled
upstream must stop dependent infrastructure work. In particular, BigRAE Platform
must not plan or apply on top of a failed BigRAE Engine deploy.

## Change Detection

The orchestrator uses path filters to run only relevant jobs:

| Filter | Triggers When |
|--------|--------------|
| `core` | ECR module, environment root, deploy workflow |
| `range` | Range Terraform, engine state module |
| `shifter_engine` | BigRAE Engine code, ECR module |
| `shifter_platform` | Portal/Guacamole Terraform and platform deploy workflow |
| `quality_relevant` | Any non-docs change, plus guardrail docs; controls whether Quality runs without launching deploy or Terraform plan jobs |
| `portal_image` | Portal image build inputs (`shifter/shifter_platform/**`, `installation`, `.dockerignore`); triggers the portal image build/deploy on a deploy dispatch without running Terraform |
| `gcp` | GCP Terraform, the Helm chart, GCP scripts, the GCP deploy command modules in `scripts/bootstrap`, GCP cloud adapters |
| `mcp` | MCP package changes, routed to Quality only |
| `quality_only` | Non-deploy test-support and guardrail surfaces (`scripts/stack-smoke/**`, each development pack under `shifter/environment-packs/`, `_quality.yml`, ADR/guardrail checker paths), routed to Quality only. Shipped environment packs route to `portal_image` |

## Quality Gate

Runs on every PR, merge group, direct push to `dev`/`main`, and every manual
deploy dispatch (the safety gate before an apply) unless the diff is ordinary
docs-only.
Guardrail docs such as `.github/pull_request_template.md`,
`.github/copilot-instructions.md`, `docs/adr/**`, and the ADR enforcement
guide are quality-relevant and still run Quality.

The deploy workflow exposes one `quality_relevant` output for this decision.
Non-docs changes and guardrail docs make it true.
Ordinary docs-only changes make it false. PR Gate accepts
a skipped Quality job only when `quality_relevant` is false.

Inside `_quality.yml`, the always-run path-detection job runs
`scripts/quality_ownership/classify_paths.py`, which reads the versioned
quality-ownership contract at `.github/quality-path-filters.yaml` and rejects
any unclassified changed path before it selects jobs. That contract also maps
every production path to its blocking lint, security, and test jobs; the
`quality-path-ownership` ADR guard (ADR-004-R24) enforces that ownership.
See `docs/technical/dev/adr-enforcement.md` for how to add a quality unit or
record a gap.

The blocking repository-wide owners include:

- ADR tooling: Ruff plus medium-and-higher Bandit findings.
- Stack smoke: Ruff, medium-and-higher Bandit findings, and ShellCheck.
- Standalone deployment utilities: one blocking medium-and-higher Bandit lane
  in addition to their package-local Ruff and test jobs.
- MCP packages: ESLint security rules promoted to errors, zero warning
  tolerance, package tests (including `mcp/shared`), and dependency audits.
- Container inputs: BuildKit Dockerfile checks, entrypoint ShellCheck, and
  high/critical Trivy configuration policy; the Guacamole authority test job
  builds both customized runtime images. The root `.dockerignore` is a separate
  portal-image-context owner whose test route builds and boots the production
  portal image through stack smoke.
- Helm charts: lint and render every supported values profile, then scan the
  rendered manifests with kube-linter.


The BigRAE Engine reusable workflow has an additional blocking provisioner
pytest gate before local Docker validation, credentialed image build, and ECS
deploy. This keeps a deploy dispatch from building or deploying the provisioner
image when the top-level Quality job is legitimately skipped.

- **ADR conformance**: `python3 scripts/adr_guard/adr_guard.py --all --level ci`
  Includes `adr-registry`, `layer-imports`, `cross-layer-model-imports`, and
  `cloud-factory-seam` (ADR-005-R1 cloud adapter parity).
- **Workflow linting**: `actionlint`
- **Terraform linting**: `tflint` with `tflint-ruleset-google` plugin
  The repo currently runs a narrow TFLint profile that excludes existing
  version/provider and unused-declaration debt until that backlog is burned down.
  The Google plugin adds GCP-specific rules (invalid machine types, deprecated
  attributes, etc.).
- **Python import contracts**: `lint-imports --config ../../.importlinter`
- **Python linting**: `ruff check`, `ruff format --check`
- **K8s schema validation**: `kubeconform` validates Kubernetes manifests against
  official schemas, pinned to the target GKE version.
- **K8s security and best practices**: `kube-linter` enforces security contexts,
  resource limits, privilege escalation prevention, and other best practices
  via `.kube-linter.yaml`.
- **K8s security scanning**: Checkov with the `kubernetes` framework. Current
  soft-fail is scoped to Kubernetes manifest hardening and does not justify
  Terraform soft-fail.
- **Tests**: package-local Python, JavaScript, and harness suites, including
  `shifter_platform`, `shifter/engine/provisioner`, `packer`,
  `installation`, `scripts/bootstrap`, `scripts/gcp`, `scripts/stack-smoke`, the Postgres migration proof, and MCP package
  tests including `mcp/planner`.
- **IaC scanning**: Checkov for Terraform is a **blocking gate** under
  ADR-004-R11. Pre-commit and CI share the same config at
  `platform/terraform/.checkov.yaml`; `--soft-fail` is off. Accepted-risk
  waivers (Checkov `skip-check` entries or inline `# checkov:skip=…`
  comments) require a matching entry in `docs/adr/exceptions.yaml` with
  owner, reason, expiry, affected paths, and the Checkov policy ID.
- **Secret scanning**: gitleaks on newly introduced commits
- **Coverage**: `shifter_platform` and provisioner test jobs emit XML coverage
  reports

Commit-message or label-based test skips are not accepted by `deploy.yml`.

## Terraform Flow

Authorized deployment jobs initialize and validate the selected root before creating a saved plan.
The common lock timeout is five minutes:

```text
terraform plan -lock-timeout=5m -out=tfplan
terraform apply -lock-timeout=5m tfplan
```

The job supplies its protected backend and deployment values before these commands.
Individual reusable workflows retain their own job dependencies and readback checks.
Pull requests and pushes validate; they do not authorize infrastructure apply.
Manual dispatches queue by deployment so another run cannot cancel an active mutation.
Newer commits may cancel pull-request validation because it performs no apply.

The saved plan file created inside the apply job is the apply contract. If state
moves after that local plan, Terraform should fail the saved-plan apply instead
of silently executing a fresh unplanned apply. Raw binary plans are not uploaded
as workflow artifacts because they can include unredacted plan/state data. The
platform Service Discovery replacement check reads the same saved `tfplan` that
the apply step consumes.

**Note**: The committed `terraform.tfvars` files ship an `example.com`
baseline. Deployment-specific values (domains, alarm emails, allow-list
domains, account-suffixed bucket names, GCP project id, etc.) come from
GitHub repository variables and secrets at deploy time; CI/CD renders
them into a gitignored `local.auto.tfvars` before `terraform apply`.
See [`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md)
for the required surface.

## AWS Platform Deployment

This reference describes `_shifter-platform.yml` inside the orchestrator's AWS dependency chain.
Use [developer setup](setup.md#aws-deployment) for authorized contributor deployment.
Published AWS installation support is planned.

| Job | Current responsibility |
| --- | --- |
| `push-guacamole-images` | Build and attest Guacamole images when platform inputs require it |
| `apply` | Initialize the portal data-plane root, create a saved plan, apply it, and check infrastructure readback |
| `build` | Build the portal image after Guacamole images succeed or are legitimately skipped |
| `eks-deploy` | After a successful build, render protected config, backend inputs, and exact image digests; invoke the EKS lifecycle |
| `post-deploy-smoke` | Run the configured development smoke and retain its separate failure result |

`build` does not depend on a legacy ECS/ASG portal apply.
The EKS lifecycle owns its isolated Terraform root and shared Helm deployment.
It provisions database prerequisites, runs migrations through the dedicated owner duty, and verifies workload and admission boundaries.
The image tag is `<short-sha>-<run-id>-<run-attempt>`; deployment consumes the digest.
There is no `latest` deployment identity.

Earlier SSM deployment, portal instance refresh, and Guacamole ECS stabilization steps do not describe the current EKS path.
Do not use their topology outputs or `DB_IAM_AUTH_RUNTIME` switches to recover EKS workloads.
See [EKS operations](../../ops/portal-eks-operations.md) and [AWS native identity](../../ops/aws-native-identity.md).

### First-run DNS timing

On a fresh account, publish SES validation records from the portal data-plane outputs.
The EKS root supplies ingress certificate validation through `bundle_outputs.ingress_certificate_dns_records`.
Publish those records in the authoritative DNS zone, then verify certificate issuance before routing application traffic.
See [deployment secrets and DNS](../../dev/deploy-secrets.md) for the current output owners and routing procedure.

## Environment Detection

```
Event / input                  → Behavior
Pull request                   → Quality only
Push to dev / main             → Quality only
dispatch environment=aws-dev   → AWS dev deploy
```

## Provider Routing

- `dev`/`main` are integration branches: they run the quality gate but never plan/apply infrastructure or deploy workloads.
- A deploy is a manual `workflow_dispatch` that names the `environment`; the branch you run it from is the code that deploys. No branch name selects the target.
- The GCP control plane is deployed through the Helm chart in `platform/charts/shifter` by `scripts/bootstrap/deploy.py gcp-deploy`, with generated values layered on top of the profile values. CI and an operator without GitHub run the same command (ADR-070).
- The GCP portal auth contract is FirebaseUI/browser-side Identity Platform auth plus server-side verified-token exchange. Do not add Django credential handling to recreate Cognito semantics.
- Multi-cloud work enters through the shared cloud adapter layers rather than provider-specific calls in domain services.

## Manual Deploy Inputs

`deploy.yml` runs on `workflow_dispatch`. The `environment` input selects the deployment target; the bootstrap flags are strict by default.

- `environment`: the closed deployment choice currently contains only `aws-dev`.
  The selected ref supplies the code.
  No GCP target is selectable.
- `aws_first_deploy` (default `false`): allow the AWS engine deploy to skip the ECS task-family existence check. Set `true` only for the first-ever deploy to a fresh AWS environment, before the platform Terraform apply has created the provisioner task definition. On any normal deploy, a missing or misspelled task family fails the run. Clear the flag once the platform stack has been applied.
- `gcp_require_active_certificate` (default `true`): require the GKE ManagedCertificate to be Active for the public hostname. Set `false` only for first-time GCP bootstrap, before DNS for the hostname has been pointed at the ingress IP.

## Runner Policy

Workflows choose one runner class per job. Portable quality jobs run on
`ubuntu-latest`; trusted deployment, image-build, Packer, and
environment-mutating jobs run on `self-hosted` runners. GitHub Actions does not
provide native fallback between those runner classes.

The self-hosted runner has:

- AWS CLI configured
- gcloud SDK support for GCP workflows
- Docker + BuildX
- Terraform (AWS deploy jobs pin `1.13.3`; GCP deploy jobs pin `1.17.1`)
- Python 3.12
- Network access to AWS and GCP APIs

## Viewing Logs

1. Go to Actions tab in GitHub
2. Select the workflow run
3. Expand the job you want to inspect
4. Each step shows its logs

Keep full Terraform plans in the approved private evidence boundary.
Only redacted summaries belong in public review records.

## Common Issues

<a id="workflow-doesnt-trigger"></a>

### Workflow Does Not Trigger
- Check branch protection rules
- Verify path filters match your changes
- Look for `paths-filter` in deploy.yml
- A deploy is a manual dispatch: `gh workflow run deploy.yml --ref <branch> -f environment=aws-dev`. Pushes and PRs run validation only; no branch push deploys.

### Terraform Plan Fails
- Check for formatting issues: `terraform fmt -recursive`
- Validate locally first: `terraform validate`
- Review the error in the Actions log

### Docker Build Fails
- Check Dockerfile syntax
- Verify base image availability
- Review build logs for dependency issues

### Deploy Fails

- Check the exact failed job and its selected protected environment.
- For EKS, inspect the normal lifecycle output, rollout, admission checks, and authenticated health.
- Use [RB012](../../runbooks/rb012-portal-deployment.md) and the EKS operations guide.
- Retired EC2 portal SSM commands do not diagnose current EKS application workloads.

### GCP Deploy Fails

No GCP workflow target is currently selectable.
Use [RB023](../../runbooks/rb023-gcp-deployment.md) for the release-driven deployment path.
The following points describe the retained CI adapter if an authorized target is added.
- Verify each purpose Environment has its explicit `GCP_*_SERVICE_ACCOUNT` and `GCP_WORKLOAD_IDENTITY_PROVIDER` secrets set
- Check the `Render deployment inputs` step: the CI adapter stops when a required input is missing or when a GitHub value conflicts with the root config
- Check the `Run the infrastructure stage` step for IAM or bucket-name conflicts on the GCS backend bucket. The step log shows each command that ran and the error of the command that failed
- The command keeps the Terraform outputs, the runtime env, and the generated Helm values in a private temporary directory, not in the workflow log. Review the ingress resources and the `BackendConfig` resources if hostname, DNS, certificate, or Cloud Armor behavior is wrong
- Review the `guacamole-runtime` Secret sync in the `Run the rollout stage` step if the Guacamole client pods stay in `CreateContainerConfigError`
- If portal authentication fails, verify `public_hostname` and `managed_tls_enabled=true` in the Terraform outputs.
  Check Identity Platform, its blocking function, and MFA configuration.
  Confirm that bootstrap operator credentials were supplied and the managed certificate reaches `Active`.
- Check `kubectl rollout status` output for the specific control-plane deployment that stalled
