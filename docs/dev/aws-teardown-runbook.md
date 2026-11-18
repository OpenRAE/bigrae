# AWS environment teardown

Part of the BigRAE deploy and operations docs; start at the [documentation home](../index.md).

Use this how-to guide to retire one authorized AWS contributor deployment.
It covers Terraform layers, owned residuals, and separately approved control-plane cleanup.
It reverses [the AWS apply order](aws-terraform-apply-order.md).

The `aws-env-destroy.yml` workflow invokes `scripts/bootstrap/aws_env_destroy.py` on GitHub-hosted compute.
Its current target is `dev`; it retains the bootstrap state bucket, GitHub Environment, and deployment secrets.
Source tests do not establish live teardown qualification.
The historical qualification work is tracked in #2044.

Before teardown, approve the deployment, backups, data loss, downtime, costs, and cleanup boundary.
Stop new admission and conflicting work, then drain or destroy ranges through their owning lifecycle.
For an active EKS application, run its normal `eks-teardown` lifecycle first.
That lifecycle removes Helm resources before destroying the isolated EKS root.
The environment script orders non-empty EKS state first, but does not invoke the Helm uninstall lifecycle itself.
Do not assume direct cluster destruction cleans up controller-created load balancers.

> **Destroys real infrastructure.** Run only against the intended environment.
> Confirm the active AWS profile and account id before every destructive step:
> `aws sts get-caller-identity`.

## CI teardown architecture guardrails (#1287)

The manual sequence below is also the architecture contract for any automated
AWS environment destroy. The GCP teardown (`deploy.py gcp-destroy`) has
provider-specific resource semantics, so it is not an AWS teardown contract.

### Contract conflicts to resolve before implementation

The source implements EKS, Portal, Range, Core, runner, then IAM order.
Empty state is skipped; unknown state or failed queries do not establish absence.
EKS precedes the data services and range networking it consumes.
Portal precedes Range and Core because it reads their state and owns cross-stack resources.
The runner root precedes IAM because teardown runs outside that runner fleet.
IAM remains last so earlier operations retain their authentication path.

Do not reuse earlier issue proposals that placed IAM before runners or omitted EKS.
Do not depend on one STS session remaining valid throughout a long teardown.

### Security and configuration boundaries

- Use a closed `choice` input following `deploy.yml`'s public environment names
  (`aws-dev`) and map once to the Terraform name (`dev`) and
  GitHub Environment names. Prod is not an implied target. Reject every unknown
  value before checkout or cloud authentication; never construct a secret name
  dynamically from free-form input.
- Validate the exact `DESTROY` confirmation before cloud authentication. Bind
  every credentialed/mutating job to the selected `aws-*` GitHub Environment;
  that binding is how the job selects the environment's OIDC deploy role and
  secrets. The teardown reuses the existing `github-actions-shifter-<env>`
  deploy role (the same principal `deploy.yml` assumes), so it adds no new IAM
  trust surface. ADR-004-R23 governs the separate Packer image role. The shared deploy role uses its own trust policy; review its current protected subjects before teardown.
- Run on GitHub-hosted compute outside the target account. Checkout the event
  commit (`github.sha`) with `persist-credentials: false`; keep job permissions
  to `contents: read` and `id-token: write`; pin every external action to a full
  commit SHA under ADR-037-R1.
- Resolve `AWS_ROLE_ARN_DEV` and
  `TF_INFRA_STATE_BUCKET_DEV` through the existing explicit environment
  selection and `scripts/bootstrap/preflight.py` conventions. Verify the STS
  caller is the account encoded by the selected role without printing either
  value. Keep the repository's single AWS region input (`us-east-2` today) as
  one value, not repeated per service.
- Render every backend with
  `scripts/terraform/render_aws_backend_configs.py`. That is the canonical
  environment and bucket validator and writes all state-key mappings through
  `scripts/bootstrap/terraform_backend.py`; do not parse or rewrite committed
  `*.s3.tfbackend` placeholders in workflow shell.
- Terraform destroy still evaluates variables and data sources. Reuse the
  existing `TF_VARS_<ENV>_{CORE,RANGE,PORTAL}` and
  `SHIFTER_CONFIG_<ENV>_RANGE` rendering paths rather than relying on committed
  example values. Treat those payloads as sensitive: write them under the
  runner's temporary workspace, never echo them, put them in argv, upload them,
  or enable shell tracing. The runner root must also reproduce its applied
  network topology from positive state evidence, never from absence (#1437).
  `aws_env_destroy.py` passes `create_runner_network=true` when
  `module.runner_network` is in state, and `allow_default_vpc=true` when
  `data.aws_subnets.default` is in state. With neither, it reads the applied
  `vpc_id` and `subnet_id` back from the runner security group and instances in
  state. When that VPC appears in the default VPC IDs recorded by
  `data.aws_vpcs.default`, the default-VPC exception was applied with an
  explicit subnet, so it also passes `allow_default_vpc=true`. It fails closed
  before the runner destroy when any of that evidence is missing or ambiguous.
- Serialize against `deploy.yml` with the same per-environment concurrency key
  and `cancel-in-progress: false`. A deploy, destroy, or second destroy must not
  race the same Terraform state or be cancelled while mutating it. Preserve the
  existing `-lock-timeout=5m` convention for every Terraform operation.

### Ownership, cleanup, and evidence boundaries

- Terraform state is authoritative. Derive pre-destroy RDS, EC2, S3, and KMS
  targets from the selected stack state where possible, then cross-check the
  live account, canonical name, and `Project=shifter`, `Environment=<env>`, and
  `ManagedBy=terraform` tags. A name or tag alone is not deletion authority.
  The runner root lacks an Environment default tag, so it must be addressed by
  its selected state, not swept by a broad tag query.
- Lift protection only on proven-owned resources. Cover both Portal and
  Guacamole RDS instances and the repository's other deletion-protection
  surfaces (ALB, Cognito, Portal inspection firewall) when the
  selected configuration enabled them. EC2 stop/termination protection must be
  disabled on the exact owned instances before deletion; do not mutate every
  protected instance in the account.
- Empty only state-owned S3 buckets, including every current object, version,
  delete marker, and incomplete multipart upload. Writers can refill log
  buckets during teardown, so re-check immediately before their bucket resource
  is deleted. Preserve ECR until Portal's `aws_ecr_image` data sources have
  evaluated, as described below.
- AWS KMS keys normally converge through scheduled deletion; unlike GCP key
  rings, they are not intrinsically unremovable. Never pre-emptively `state rm`
  all KMS resources. Remove only the exact state address implicated by a known
  destroy failure, record that exception visibly, and still require its alias to
  be absent. A pending-deletion key is distinct from a live alias.
- Reuse `scripts/bootstrap/account_recovery.py`'s safety semantics: an API error means unknown/failure, not absence. Ownership requires name and tags where available. AWS commands use argv lists without `shell=True`. Reports omit secret values and raw API bodies. Do not weaken that command's structural ban on
  deleting data-bearing resources. If teardown needs adjacent tested sweep
  support, share only the read-only query/ownership/reporting primitives and
  keep the stronger destructive authorization explicit to this teardown.
- Paginate every inventory. Wait within defined limits for deletion and consistency. Fail final verification when any required service could not be queried. Distinguish absent, deleted, blocked ownership, and failed query/delete results. Emit `::error::` and a nonzero exit on failure. Report only safe resource classes, counts, and names.

The bootstrap-created, versioned Terraform state bucket is not tagged with the
environment and is not owned by any Terraform root. Issue #1287 does not
currently say to delete it or the corresponding GitHub secrets/Environment.
Exclude the resolved state bucket from generic S3 cleanup. The workflow retains it. A separately approved final retirement may remove it only after every state operation finishes.

The extensibility seam is the single closed AWS environment binding (public
choice, Terraform environment, GitHub Environment, role secret, state-bucket
secret, and region) plus the canonical backend stack inventory. A future AWS
environment or supported state root extends those seams once. It must not add
another provider-neutral destroy abstraction, duplicate secret schema, or a
second set of state keys.

## Manual destroy order

Remove active EKS application resources through `eks-teardown` first.
The remaining environment order is EKS state, Portal, Range, Core, runner, then IAM.
Portal must precede Range and Core because it reads their remote state. Each
stack initializes with its own `-backend-config=<env>.s3.tfbackend`.

## 1. Lift deletion protection (prod, and any env that enabled it)

Several resources ship deletion protection on (secure default in prod; `false`
in dev, so dev usually need no change). For any environment where
these are `true`, set the tfvars to `false` and `terraform apply` the owning
stack first, so the live resource drops protection before destroy:

| Resource | tfvars input | Stack |
|---|---|---|
| Portal RDS | `db_deletion_protection` | Portal |
| Guacamole RDS | `guacamole_db_deletion_protection` | Portal |
| Portal ALB | `enable_deletion_protection` (prod hardcoded `true`) | Portal |
| Portal inspection Network Firewall | `portal_inspection_delete_protection` | Portal |
| Cognito user pool | `deletion_protection` (`ACTIVE`/`INACTIVE`) | Portal |

The prod portal ALB protection is a hardcoded `true` literal
(`environments/prod/portal/main.tf`); flip it to `false` and apply before
destroy.

## 2. Empty the Portal S3 buckets (before the Portal destroy)

No S3 bucket sets `force_destroy`, so a non-empty bucket blocks its stack
destroy. Empty the Portal-owned buckets before the Portal destroy:

- Portal user-storage bucket.
- Log-aggregation `logs` and `alb_access_logs` buckets.
- Engine state bucket (`engine-state` module; `force_destroy = false`).

Empty a versioned bucket by bulk-removing current objects, then sweeping old
versions and delete markers:

```bash
aws s3 rm "s3://$BUCKET" --recursive           # fast bulk of current versions
# then delete remaining versions + delete markers:
aws s3api list-object-versions --bucket "$BUCKET" \
  --query 'Versions[].{Key:Key,VersionId:VersionId}' --output json > /tmp/v.json
aws s3api delete-objects --bucket "$BUCKET" --delete "{\"Objects\": $(cat /tmp/v.json)}"
# repeat for DeleteMarkers[] until both are empty.
```

**Do NOT empty the ECR repos yet.** The guacamole module resolves the `guacd`
and `guacamole-client` image digests through `data "aws_ecr_image"` sources that
are evaluated during the Portal destroy plan. If the repos are empty at that
point, the Portal destroy fails with a data-source lookup error. Empty ECR only
in step 3, after the Portal (and Range) destroys, right before the Core destroy.

## 3. Destroy the stacks

Before these retained manual commands, complete the authorized EKS lifecycle teardown.
Then destroy Portal before Range. The Portal stack requires the
`terraform_state_bucket` variable (normally in the CI-rendered remote-state
tfvars); pass it explicitly if you do not have that file locally. Init each
stack against the real state bucket:

```bash
STATE_BUCKET=<the shifter-<env>-infra-<uuid> bucket>
cd platform/terraform/environments/<env>/portal
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve -var="terraform_state_bucket=$STATE_BUCKET"

cd ../range
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve
```

Now empty the four ECR repos (Core stack owns them; prod drops the `<env>-`),
then destroy Core:

```bash
for r in shifter-<env>-portal shifter-<env>-pulumi-provisioner \
         shifter-<env>-guacd shifter-<env>-guacamole-client; do
  aws ecr batch-delete-image --repository-name "$r" \
    --image-ids "$(aws ecr list-images --repository-name "$r" --query 'imageIds[*]' --output json)"
done

cd ../          # environments/<env>/ (Core)
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve
```

A KMS or deletion-protection failure requires investigation of the exact owned resource and state address.
AWS keys normally use scheduled deletion; do not copy GCP key-retention behavior to AWS.
Do not remove state merely to report success.
Any exceptional state removal needs an approved cleanup plan, exact address, retained recovery evidence, and independent provider readback.

### Known destroy stalls and fixes

These are historical failure patterns that may affect retained resources.
Confirm current ownership and stopped writers before a direct cleanup action.
They do not authorize broad deletion or changes to another deployment:

- **Redis rotation Lambda ENI blocks the SG and private subnet.** A retained Redis rotation Lambda can delay security-group and private-subnet deletion for over 20 minutes. Its VPC ENI may remain after function deletion. Confirm exact ownership and `Status=available` before reviewed cleanup. Once the ENI shows
  `Status=available` it is safe to delete manually, which unblocks Terraform's
  next retry:
  ```bash
  aws ec2 describe-network-interfaces \
    --filters Name=description,Values="AWS Lambda VPC ENI-*redis-rotation*" \
    --query 'NetworkInterfaces[?Status==`available`].NetworkInterfaceId' --output text
  aws ec2 delete-network-interface --network-interface-id <eni-id>
  ```
- **Log buckets refill during the destroy.** Log writers can refill buckets after the first emptying. Terraform can then return `BucketNotEmpty` or HTTP 409. Stop the owners and recheck before bucket deletion. Re-empty those two buckets
  after the writers are gone and re-run the destroy; it then deletes them.
- **`data "aws_ecr_image"` fails when ECR is already empty.** Covered in step 2:
  do not empty the guacamole ECR repos before the Portal destroy. If you already
  did, push any throwaway image tagged with the expected tag (`1.5.5`) to
  `shifter-<env>-guacd` and `shifter-<env>-guacamole-client` so the data sources
  resolve, then destroy.
- **CloudWatch log groups survive the range destroy and block a fresh apply.**
  In-flight log delivery can recreate range flow-log, Network Firewall, or Route53-resolver log groups during destroy. Examples are `/vpc/<env>-range-flow-logs`, `/aws/network-firewall/<env>-range`, and `/aws/route53/resolver/<env>-range`. Successful stack destruction alone does not prove these groups are absent. Nothing has `skip_destroy`; the fix is a post-destroy
  sweep. A later fresh apply otherwise fails with
  `ResourceAlreadyExistsException`. Delete any that remain:
  ```bash
  for lg in $(aws logs describe-log-groups \
    --query 'logGroups[?contains(logGroupName,`<env>-range`)||contains(logGroupName,`<env>-portal`)||contains(logGroupName,`/vpc/`)].logGroupName' \
    --output text); do aws logs delete-log-group --log-group-name "$lg"; done
  ```

### Broader leftover sweep (resources that block a fresh apply)

**Automated path (preferred).** The bootstrap CLI's `account-recovery` command now
detects (and, with `--sweep`, deletes) most of this leftover set for you, instead of
running the class-by-class `aws` commands below by hand:

```bash
# Read-only detection:
./scripts/bootstrap/deploy.py account-recovery --env "$ENV" --profile <profile>
# Detect and delete the owned leftovers:
./scripts/bootstrap/deploy.py account-recovery --env "$ENV" --profile <profile> --sweep
```

It refuses live tenants and requires matching names plus `Project=shifter` and `Environment=<env>` tags. It excludes data-bearing resources. Asynchronous Network Firewall deletes are checked until completion. It covers AWS Budgets, RDS parameter groups/event subscriptions, EventBridge schedules, portal `/shifter/<env>/portal` SSM parameters, ECR repositories, KMS aliases, and Network Firewall rule groups. See
`scripts/bootstrap/README.md` for the full safety model.

RDS DB subnet groups, the ElastiCache subnet group, EC2 key pairs, and security groups remain manual. Their sections below are marked _(manual)_. Run those after `account-recovery` reports clean.

The env stacks manage every resource below, so a clean `terraform destroy`
removes them. They can remain after an incomplete destroy. Deleting the state bucket first also orphans resources by removing their managed ownership record. A later fresh bootstrap starts from
empty state and collides (`AlreadyExists` / `ResourceAlreadyExistsException`).

This is the #1472 leftover set. Run this sweep after the Portal/Range/Core
destroys report success. Discovery is read-only; delete only what the discovery
lists.

Set the environment and account first:

```bash
ENV=<env>                                                   # dev | prod
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

`aws ... --query` uses JMESPath single-quote string literals so the surrounding
double-quoted shell string does not trigger backtick command substitution.

- **AWS Budgets** (`shifter-<env>-s3-cost-alert`, account-scoped, Core stack):
  ```bash
  aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
    --query "Budgets[?starts_with(BudgetName, 'shifter-$ENV-')].BudgetName" --output text
  aws budgets delete-budget --account-id "$ACCOUNT_ID" --budget-name "shifter-$ENV-s3-cost-alert"
  ```
- **RDS DB parameter groups** (`<env>-portal-postgres-pg`, `<env>-portal-guacamole-postgres-pg`):
  ```bash
  aws rds describe-db-parameter-groups \
    --query "DBParameterGroups[?starts_with(DBParameterGroupName, '$ENV-portal')].DBParameterGroupName" --output text
  aws rds delete-db-parameter-group --db-parameter-group-name <name>
  ```
- **RDS DB subnet groups** _(manual)_ (`<env>-portal-db-subnet`, `<env>-portal-guacamole-db-subnet`):
  ```bash
  aws rds describe-db-subnet-groups \
    --query "DBSubnetGroups[?starts_with(DBSubnetGroupName, '$ENV-portal')].DBSubnetGroupName" --output text
  aws rds delete-db-subnet-group --db-subnet-group-name <name>
  ```
- **ElastiCache subnet group** _(manual)_ (`<env>-portal-redis`):
  ```bash
  aws elasticache describe-cache-subnet-groups \
    --query "CacheSubnetGroups[?starts_with(CacheSubnetGroupName, '$ENV-portal')].CacheSubnetGroupName" --output text
  aws elasticache delete-cache-subnet-group --cache-subnet-group-name "$ENV-portal-redis"
  ```
- **EventBridge Scheduler schedules** (`<env>-portal-cognito-rotation-reminder`; the
  dev-box `shifter-dev-box-nightly-shutdown` only if the `global/dev-box` stack was
  applied and you are retiring it):
  ```bash
  aws scheduler list-schedules \
    --query "Schedules[?starts_with(Name, '$ENV-portal')].Name" --output text
  aws scheduler delete-schedule --name <name>
  ```
- **SSM parameters** under `/shifter/<env>/portal` (~38). Enumerate names only; do
  not print values. The range AMI params live under `/shifter/ami/*` and are
  outside this path, so they are preserved:
  ```bash
  aws ssm get-parameters-by-path --path "/shifter/$ENV/portal" --recursive \
    --query 'Parameters[].Name' --output text | tr '\t' '\n' | \
    while read -r p; do [ -n "$p" ] && aws ssm delete-parameter --name "$p"; done
  ```
- **EC2 key pairs** _(manual)_ (`<env>-portal-ctfd-ssh`):
  ```bash
  aws ec2 describe-key-pairs \
    --filters "Name=tag:Project,Values=shifter" "Name=tag:Environment,Values=$ENV" \
    --query "KeyPairs[?starts_with(KeyName, '$ENV-portal')].KeyName" --output text
  aws ec2 delete-key-pair --key-name "$ENV-portal-ctfd-ssh"
  ```
- **RDS event subscriptions** (`<env>-portal-db-backup-events`):
  ```bash
  aws rds describe-event-subscriptions \
    --query "EventSubscriptionsList[?starts_with(CustSubscriptionId, '$ENV-portal')].CustSubscriptionId" --output text
  aws rds delete-event-subscription --subscription-name "$ENV-portal-db-backup-events"
  ```
- **Security groups** _(manual)_ (`<env>-portal*`, tagged `Project=shifter`). A leftover SG
  usually lingers because an ENI still references it (the redis rotation SG stall
  above is the common case); delete it once the ENI is gone. Never delete a VPC
  `default` SG:
  ```bash
  aws ec2 describe-security-groups \
    --filters "Name=tag:Project,Values=shifter" "Name=tag:Environment,Values=$ENV" \
    --query "SecurityGroups[?GroupName!='default' && starts_with(GroupName, '$ENV-portal')].[GroupId,GroupName]" --output text
  aws ec2 delete-security-group --group-id <sg-id>
  ```

## 4. Destroy the runner root and deregister runners

```bash
# Deregister each runner from GitHub first. Mint the remove token in your clone:
#   REPO="$(gh repo set-default --view)"
#   TOKEN=$(gh api -X POST "/repos/$REPO/actions/runners/remove-token" --jq .token)
# Then run these commands on the EC2 via SSM with that token:
#   cd /home/ec2-user/actions-runner
#   sudo ./svc.sh stop && sudo ./svc.sh uninstall
#   sudo -u ec2-user ./config.sh remove --token "$TOKEN"
./scripts/runner-deploy.sh --destroy
```

`runner-deploy.sh --destroy` uses `dev.tfvars`, which selects the managed runner
network, so it matches only a fleet applied on that network. For a fleet applied
with `--use-existing-network`, run `terraform destroy` in
`platform/terraform/global/github-runner` with `-var=create_runner_network=false`
and the same `vpc_id`/`subnet_id` it was applied with. The automated teardown
resolves the applied topology from state for you.

See [`aws-runner-provisioning-runbook.md`](aws-runner-provisioning-runbook.md).

## 5. Destroy the global/iam stack, then the state backend

The `global/iam` stack (applied by bootstrap, not by `deploy.yml`) owns the
GitHub OIDC provider, the `github-actions-shifter-<env>` deploy role, its five
permission policies, and the `shifter-<env>-ci-role-boundary` policy.
`terraform destroy` of the env stacks does not touch any of it. **Destroy
`global/iam` before deleting the state bucket** (the bucket holds its state).
Skipping this is the #1431 failure: a later fresh bootstrap starts from empty
state and collides with these surviving resources (`EntityAlreadyExists` on the
CI boundary policy).

```bash
cd platform/terraform/global/iam
terraform init -reconfigure -backend-config=<env>.s3.tfbackend -backend-config="bucket=$STATE_BUCKET"
terraform destroy -auto-approve -var-file=<env>.tfvars
```

Also delete any stray temporary `github-actions-shifter-<env>-bootstrap` role
(bootstrap normally removes it).

**Then** empty and delete the `{uuid}` state bucket
(`shifter-<env>-infra-<uuid>` for dev, `shifter-infra-<uuid>` for prod).
It is versioned; delete all object versions and delete markers, then the bucket.

## 6. Clear local operator config

```bash
rm -rf ~/.shifter/<env>-<bucket>/
```

## 7. Delete the GitHub environment and its secrets

Delete the environment-scoped and per-env deploy secrets for the environment
being retired (for example `AWS_ROLE_ARN_DEV`, `TF_INFRA_STATE_BUCKET_DEV`,
`TF_VARS_DEV_*`, `SHIFTER_CONFIG_DEV_RANGE`, `SMOKE_*`). Keep shared/prod
secrets (`AWS_ROLE_ARN`, `TF_INFRA_STATE_BUCKET`, `TF_VARS_PROD_PORTAL`,
`SONAR_TOKEN`, `PLATFORM_BOOTSTRAP_STAFF_EMAILS`,
`PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`). See
[`deploy-secrets.md`](deploy-secrets.md) for the full list.

## 8. Verify the account is empty

Before fresh bootstrap, independently inventory EC2, ASG, RDS, ALB, Network Firewall, ECR, IAM, CloudWatch log groups, and state storage. Confirm selected `github-actions-shifter-*` roles and `shifter-<env>-*` policies match the approved retirement boundary. Retained workflow state is not an empty account.

Check the broader residual set too: cost-alert budget, RDS parameter/subnet groups, ElastiCache subnet group, schedules, SSM parameters, EC2 key pairs, and security groups. Include the portal backup event subscription. Use exact state and ownership evidence, not a wildcard deletion rule.

If any remain, re-run the §3
broader leftover sweep. Preserve only what you intend to reuse (for example range
AMIs and their `/shifter/ami/*` SSM parameters).
