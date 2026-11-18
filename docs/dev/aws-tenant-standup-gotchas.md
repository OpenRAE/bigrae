# AWS tenant standup gotchas

Part of the BigRAE deploy and operations docs; start at the [documentation home](../index.md).

This how-to guide records AWS setup conditions that need operator action. It distinguishes historical workarounds from current supported deployment interfaces. Fixes
that belong in the scripts, workflows, or Terraform go into the code, not here.
Use this alongside the authoritative runbooks:
[`deploy-secrets.md`](deploy-secrets.md),
[`aws-terraform-apply-order.md`](aws-terraform-apply-order.md),
[`aws-runner-provisioning-runbook.md`](aws-runner-provisioning-runbook.md),
[`aws-ami-seeding-runbook.md`](aws-ami-seeding-runbook.md), and
[`scripts/bootstrap/README.md`](https://github.com/Brad-Edwards/bigrae/blob/dev/scripts/bootstrap/README.md).

## Re-pointing an existing tenant at a new account ("moved account")

When an environment (for example `aws-dev`) is moved to a different AWS account,
its GitHub Actions **repository-level** `_<ENV>` secrets and variables still point
at the old account. Nothing repoints them automatically; only two of them are
bootstrap-owned. Repoint the rest by hand before the first deploy, or the deploy
runs against a mix of the new role and old-account resource IDs.

Bootstrap-owned (rewritten by `deploy.py bootstrap --env <env>`):

- `AWS_ROLE_ARN_<ENV>`
- `TF_INFRA_STATE_BUCKET_<ENV>`

Operator-owned, account-specific; must be regenerated/repointed for the new
account:

- `TF_VARS_<ENV>_CORE`, `TF_VARS_<ENV>_PORTAL`, `TF_VARS_<ENV>_RANGE`: these carry
  account-suffixed bucket names, domains, alarm email, `vm_series_ami_id`, etc.
  Regenerate from local `local.auto.tfvars` overlays with
  `scripts/sync-deploy-secrets.sh --env <env>`.
- `SHIFTER_CONFIG_<ENV>_RANGE`: the deployment `bigrae.yaml`.
- `AWS_IMAGE_ROLE_ARN_<ENV>`: from the new account's
  `platform/terraform/global/iam` output `github_actions_image_role_arn`.
- Repository **variables** `PACKER_BUILD_{VPC,SUBNET}_ID_<ENV>` and
  `PACKER_VERIFY_{SUBNET,SG,INSTANCE_PROFILE}_<ENV>`: VPC/subnet/SG IDs are
  account-specific. The verify instance profile name is deterministic
  (`shifter-<env>-range-range-instance`) but must exist in the new account after
  the range apply.

Compare a known variable, such as `PACKER_BUILD_VPC_ID_<ENV>`, with actual target-account VPC IDs. A mismatch indicates an old account's value.

## Non-TTY / headless bootstrap needs `--yes`

`deploy.py bootstrap|terraform|full` run without a terminal (an automation
wrapper, CI, an agent) must pass `--yes`. Without it the routine proceed prompts
fall to their non-interactive fallback and the GitHub-secret and backend-config
steps are skipped. `--yes` never authorizes the `account-recovery` sweep, which
always needs its own `--sweep`.

## Standalone `runners` needs `TF_INFRA_STATE_BUCKET` exported

`deploy.py runners --env <env> --profile <p>` (the standalone path, not `full`)
does not thread the bootstrap state bucket, so it resolves it from the
`TF_INFRA_STATE_BUCKET` environment variable. Export it to the bootstrap bucket
before running, or the runner apply fails closed with `Set TF_INFRA_STATE_BUCKET
or pass the bootstrap bucket name`. (The `full` path threads it automatically.)

## First-deploy AMI ordering (Core → Range → seed AMIs → Portal)

A dispatch coordinates the full chain, but Portal reads `/shifter/ami/*` as data sources. Packer verification needs `PACKER_VERIFY_*` values for a range profile, subnet, and security group. Apply Range before image verification. So a fresh account cannot
complete Portal on the first dispatch. The order is: dispatch once (Core + Range
apply; Portal fails on missing AMIs), set `PACKER_VERIFY_*` from the applied
range, seed `/shifter/ami/*` via `packer.yml`, then dispatch again to complete
Portal.

## `PACKER_VERIFY_*` values and the verify security group

After the Range stack applies, set the fresh-boot verify-gate variables from it:

- `PACKER_VERIFY_INSTANCE_PROFILE_<ENV>` = range output
  `range_instance_profile_name` (`shifter-<env>-range-range-instance`).
- `PACKER_VERIFY_SUBNET_ID_<ENV>` = the range VPC's `ssm-endpoints` subnet (or
  any range-VPC subnet; the ssm/ssmmessages/ec2messages interface endpoints have
  private DNS and are reached VPC-locally, and the endpoint SG allows 443 from the
  whole VPC CIDR).
- `PACKER_VERIFY_SG_<ENV>` = a **no-inbound, egress-all** security group. The range stack supplies no dedicated verifier security group. Its default security group has no egress. Create a reviewed verifier group tagged `Project=shifter,Purpose=packer-verify` in the range VPC. This is operational AMI-pipeline
  infra, not range Terraform, so it does not appear in the range plan.

## No AWS pre-promoted DC bake (`/shifter/ami/dc`)

`/shifter/ami/dc` must be a **pre-promoted** `internal.shifter` DC:
`_should_promote_dc_at_runtime()` is hard-disabled, so runtime promotion never
happens. AWS `dc.pkr.hcl` builds only a *generalized* Windows image (AD DS
installed, not promoted) and runs `sysprep` (which is incompatible with a
promoted DC), and the runbook forbids publishing it as `/shifter/ami/dc`. The promoted bake `a2_setup.ps1` is GCP-only.

AWS entries in `shifter/packer/dc-amis.json` refer to manually created, account-scoped images. They cannot be reused in another account. A new account therefore has no valid
DC AMI.

Real fix: implement a pre-promoted DC bake for AWS (port GCP's
`a2_setup` promotion, drop sysprep) or manually promote+capture one, then update
`dc-amis.json` / seed `/shifter/ami/dc`. A missing valid DC image blocks the complete Portal plan. Do not seed `/shifter/ami/dc` with a placeholder to bypass that prerequisite.

Prepare a correct account-owned DC image first.

## Debugging apply time Terraform bugs

The deploy workflow re-runs the ~25-min Quality gate on every dispatch, so
iterating apply time Terraform errors through CI is slow. For convergence, select the original S3 backend and rendered overlays. Review the same saved plan and apply through the authorized contributor procedure. Fix the reported cause, then validate the full chain with one approved CI dispatch.

## The active AWS portal runtime is EKS, not ECS/EC2

The legacy ECS/EC2 portal container rollout is retired: in `_shifter-platform.yml`
the `deploy` job is gated `environment == '__legacy-disabled__'` (never runs) and
`post-deploy-smoke` `needs: eks-deploy`. The earlier portal EC2/ASG application lane is retired. Applying portal data services alone does not deploy EKS workloads, migrate the application, or qualify range smoke. To stand up a working tenant, enable EKS:

- Repository variable `AWS_EKS_<ENV>_ENABLED = true` (drives `deploy.yml`'s
  `eks_enabled`, which gates `eks-deploy` and thus `post-deploy-smoke`).
- Secret `TF_VARS_<ENV>_EKS` = the full EKS root var-file JSON (see below).

The ECS/EC2 portal stack is still applied and is **not** dead: EKS reuses its
Cognito/SQS/SNS/S3/RDS. EKS runs the containers (portal/guacamole/provisioner as
pods) pointed at those resources via `runtime_env`.

## Building `TF_VARS_<ENV>_EKS`

The `eks-deploy` job feeds this JSON to the `environments/<env>/eks` root verbatim
(only injecting `deployment_role_arn`), so it must carry every required input.
There is no example file; construct it from the applied ECS/EC2 portal stack and
`aws eks`:

- `runtime_env` (map): the 12 keys in
  `shifter/installation/runtime_inventory_aws.py::AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS`.
  The provisioner topology keys (`RANGE_*`, `*_AMI_ID`, `NGFW_*`, ...) are NOT
  supplied here; the `eks-provisioner-env` module derives them from the range SSM
  export. Sources for the 12:
  - `AWS_REGION` = the region.
  - `OIDC_AUTH_DOMAIN` / `OIDC_ISSUER_URL` / `OIDC_RP_CLIENT_ID` = portal outputs
    `cognito_domain` / `cognito_issuer_url` / `cognito_client_id`.
  - `OIDC_SECRET_ID` = SSM `/shifter/<env>/portal/cognito-secret-arn`.
  - `QUEUE_{CMS,ENGINE,MC}_{CONSUMER,PUBLISHER}_ID` = SSM
    `/shifter/<env>/portal/sqs-{cms,engine,mc}-url` (consumer and publisher share
    the one queue URL).
  - `RANGE_EVENTS_TOPIC_ID` = SSM `/shifter/<env>/portal/range-events-topic-id`
    (SNS ARN).
  - `STORAGE_BUCKET_NAME` = SSM `/shifter/<env>/portal/s3-bucket`.
- `addon_versions` (object: vpc_cni, ebs_csi, efs_csi, coredns, kube_proxy,
  secrets_store_csi), from `aws eks describe-addon-versions --kubernetes-version
  <ver>`. The secrets-store add-on name is `aws-secrets-store-csi-driver-provider`
  (not `aws-secrets-store-csi-driver`).
- `domain_name` = the public hostname.
- `edge_client_cidrs` / `provider_api_cidrs`: each requires >=1 CIDR.
  `edge_client_cidrs` is the public HTTPS-ingress source allowlist (the portal is
  Cognito-gated). `provider_api_cidrs` contains pod-egress CIDRs for AWS APIs. Use approved regional API ranges and check their currency. Broader CIDRs need explicit security-owner review before deployment; they are not a default recovery shortcut.

Validate the whole thing before a CI cycle with a local
`terraform plan -var-file=<eks.tfvars.json>` (add `deployment_role_arn`) against
the `environments/<env>/eks` root using the rendered EKS backend config.

Apply `platform/terraform/global/iam` before enabling EKS so the deploy role can
manage the scoped EKS/OIDC resources and pass the `shifter-<env>-eks-*` roles.
