# Secrets Management

Where secrets live and how to manage them.

## Principles

1. **Never in code** - No secrets in source files or environment configs
2. **GitHub Secrets for CI/CD** - OIDC role ARNs plus the per-environment deploy payloads (`TF_VARS_*` and `SHIFTER_CONFIG_*`) rendered at deploy time; see [deploy-secrets.md](../../dev/deploy-secrets.md). A GCP deployment that runs without GitHub keeps no deploy input in GitHub. Its deployment config bucket holds the inputs, and Secret Manager holds the secret values (ADR-070)
3. **Cloud secret manager for runtime** - AWS Secrets Manager today, GCP Secret Manager for `gcp-dev`
4. **Explicit, not default** - No silent fallbacks; fail if secret missing
5. **Committed tfvars are non-sensitive baselines** - They contain `example.com` placeholders. Actual values use protected CI payloads or private local overlays, rendered before deployment (#1250).

## GitHub Secrets

These must be configured in repository Settings > Secrets and variables > Actions.

| Secret | Purpose |
|--------|---------|
| `AWS_ROLE_ARN` | GitHub Actions IAM role for **prod** (OIDC) |
| `AWS_ROLE_ARN_DEV` | GitHub Actions IAM role for **dev** (OIDC) |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | GitHub Actions deploy service account email in the deployment Environment of a CI-deployed GCP tenant (none exists after #2668) |
| `GCP_PACKER_BUILD_SERVICE_ACCOUNT` | Image build service account in `gcp-image-build`; the foundation bootstrap writes it |
| `GCP_PACKER_VALIDATE_SERVICE_ACCOUNT` | Image validation service account in `gcp-image-validate`; the foundation bootstrap writes it |
| `GCP_RELEASE_SCAN_SERVICE_ACCOUNT` | Exact-release scanner service account in `gcp-release-scan-<deployment suffix>` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | GitHub Actions workload identity provider resource of the GCP project that the Environment uses |
| `GCP_BOOTSTRAP_ADMIN_EMAIL` | Optional first GCP operator email for Identity Platform bootstrap |
| `GCP_BOOTSTRAP_ADMIN_PASSWORD` | Optional first GCP operator password for Identity Platform bootstrap |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | Optional comma-separated runtime staff bootstrap emails for production auth providers |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | Optional comma-separated runtime superuser bootstrap emails for production auth providers |
| `TF_INFRA_STATE_BUCKET[_DEV]` | Terraform state bucket the backend render reads (prod is unsuffixed) |
| `TF_VARS_<ENV>_CORE` / `_RANGE` / `_PORTAL` | Per-environment Terraform `local.auto.tfvars` payloads, rendered to a gitignored `local.auto.tfvars` at deploy time (since #1250) |
| `SHIFTER_CONFIG_<ENV>_RANGE` | Deployment `bigrae.yaml` payload that renders the range egress allowlist |
| `SHIFTER_CONFIG_GCP_DEV` | Deployment `bigrae.yaml` of a CI-deployed GCP environment; the CI adapter renders it into the deployment input bundle |

AWS uses IAM role ARNs for OIDC federation. A CI-deployed GCP environment uses
Google workload identity federation. A GCP deployment that runs without GitHub
uses service-account impersonation by named principals instead. No static
access keys are required.

**Deploy tfvars (since #1250)**: the committed `terraform.tfvars` are fail-loud
`example.com` baselines. Each environment's real values live in the
`TF_VARS_<ENV>_*` secrets and are rendered into a gitignored `local.auto.tfvars`
at deploy time (`*.auto.tfvars` auto-loads over `terraform.tfvars`). Push the
AWS overlays with `scripts/sync-deploy-secrets.sh`. GCP inputs are not synced
there: publish them to the deployment config bucket with
`scripts/bootstrap/deploy.py gcp-config publish`. The single authoritative
per-environment checklist is
[deploy-secrets.md](../../dev/deploy-secrets.md).

## AWS Secrets Manager

Runtime secrets accessed by the portal at startup.

### Portal Secrets

| Secret Name | Contains |
|-------------|----------|
| `shifter-{env}-portal-db-credentials` | RDS connection (host, port, user, password, dbname) |
| `shifter-{env}-portal-app` | Django SECRET_KEY, other app secrets |
| `shifter-{env}-portal-cognito` | OIDC client ID, client secret, domain |
| `shifter-{env}-portal-dc-domain` | Domain-controller domain Administrator password (`DC_DOMAIN_PASSWORD`), used by the engine provisioner to promote prebaked DC AMIs and to domain-join victims |

The domain-controller password is a live credential. It must not appear in
committed tfvars, workflow YAML, Terraform plan comments, or command logs,
only in Secrets Manager and (like every other portal secret) in restricted
Terraform state.

#### Provisioning (Terraform-managed)

The Portal Terraform root creates and seeds the DC domain password secret.
Its `random_password.dc_domain_password` value is stored in Secrets Manager.
The AWS EKS provisioner environment carries the secret reference through the existing hydration boundary.
The secret is not stored in Helm values or committed configuration.
A fresh environment uses the normal infrastructure apply; no manual secret creation is required.

### Dev Box

| Secret Name | Contains |
|-------------|----------|
| `shifter-dev-box-admin-password` | Windows Administrator password (auto-generated) |

## GCP Secret Manager

`gcp-dev` stages parallel runtime secret bundles with the same shapes the portal
already expects at startup:

| Secret Name | Contains |
|-------------|----------|
| `shifter-gcp-dev-app` | Django `SECRET_KEY`, field encryption key |
| `shifter-gcp-dev-db` | Database connection JSON bundle |
| `shifter-gcp-dev-guacamole-db` | Guacamole PostgreSQL connection JSON bundle |
| `shifter-gcp-dev-guacamole-json-auth` | Guacamole JSON auth signing key |

Current rollout behavior:

- `shifter-gcp-dev-app` and `shifter-gcp-dev-db` are seeded by Terraform for the first deployable control-plane slice
- `shifter-gcp-dev-guacamole-db` and `shifter-gcp-dev-guacamole-json-auth` are seeded by Terraform and synced into the `guacamole-runtime` Kubernetes Secret **out of band** during deploy (`kubectl apply` from Secret Manager, before the Helm release). Secret Manager and the Kubernetes Secret are the only runtime copies: these values are never placed in Helm chart values or Helm release history. The chart references the `guacamole-runtime` Secret by name only (`envFrom.secretRef`).
- Identity Platform is provisioned by Terraform for the secure GCP portal login path
- `gcp-deploy` seeds the first GCP operator from `settings.operator_bootstrap`: the `admin_email`, and the password in the Secret Manager secret that `admin_password_secret_ref` names. CI supplies `GCP_BOOTSTRAP_ADMIN_EMAIL` through the CI adapter and passes `GCP_BOOTSTRAP_ADMIN_PASSWORD` through `--operator-password-env`. The password never enters Terraform, the deployment input bundle, or a command argument
- Bootstrap operator elevation comes from `settings.operator_bootstrap.staff_emails` / `superuser_emails`, which the deploy renders into `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`. CI maps those GitHub secrets onto the settings. These values must stay out of committed source
- The same `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` contract is applied by the AWS/Cognito OIDC backend and the GCP Identity Platform backend on user login. These settings identify which authenticated users receive Django `is_staff` / `is_superuser`; they are not Django passwords and do not bypass the configured identity provider.
- GCP corporate users authenticate in the browser through Identity Platform's FirebaseUI/SDK flow. Django only accepts verified Google identity tokens and creates the application session after email-verification and MFA checks pass.
- The GCP deploy command assumes the secure portal posture. It sets the public hostname from `deployment.domain` and always enables managed TLS
- The operational dependency chain is now explicit:
  - `public_hostname` must be configured
  - managed TLS must be enabled
  - Identity Platform must be provisioned successfully
  - the public DNS record must point at the GKE ingress IP so the managed certificate can become active

## What is NOT a Secret { #whats-not-a-secret }

These are configuration, not credentials:

- AWS region
- Instance types
- AMI IDs
- S3 bucket names
- VPC CIDRs
- Domain names
- Feature flags

They do not grant access or authenticate. Actual deployment values remain outside committed source (#1250). Protected `TF_VARS_*` payloads include domains, bucket names, and CIDRs. CI renders them into gitignored `local.auto.tfvars`; see [deploy secrets](../../dev/deploy-secrets.md).

**Rule**: If it does not grant access or authenticate, it is config, not a secret.

## Adding a New Secret

### GitHub Secret

1. Go to Settings > Secrets and variables > Actions
2. Click "New repository secret"
3. Name it following existing conventions
4. Reference in workflow: `${{ secrets.SECRET_NAME }}`

### AWS Secrets Manager

1. Create via Terraform (preferred):
```hcl
resource "aws_secretsmanager_secret" "my_secret" {
  name = "shifter-${var.environment}-my-secret"
}
```

2. Or via CLI:
```bash
aws secretsmanager create-secret \
  --name "shifter-dev-my-secret" \
  --secret-string file://<private-json-file> \
  --profile $PANW_SHIFTER_DEV_PROFILE
```

3. Grant access via IAM policy in Terraform
4. Access in code via boto3 or environment variable injection

## Rotating Secrets

The bullets below are high-level operator notes, not a full production rotation
strategy. The production rotation policy per credential class is
`docs/architecture/secrets-rotation-strategy.md`; before changing production
rotation behavior, apply the architecture guardrails in
`docs/_deprecated/architecture/secrets-rotation-strategy-preflight-159.md`.

### Database Password
Current AWS runtime workloads use RDS IAM; GCP runtime workloads use native Cloud SQL authentication. Their runtime identities have no stored database password to rotate. Migration owners and Guacamole retain separate password duties.

For those duties, the process reads `DB_PASSWORD` at startup. Keep the actual database password and secret JSON consistent. Refresh affected password-duty consumers through the authorized deployment and verify their connections.

Updating only one side is not a completed rotation.

### Django SECRET_KEY
Updating `django_secret_key` in the app secret and restarting the portal
invalidates existing sessions unless explicit `SECRET_KEY_FALLBACKS` support is
added first. Do not rotate `field_encryption_key` as a side effect of rotating
`django_secret_key`.

### Cognito Client Secret
Treat this as a coordinated Cognito app-client credential swap. Keep old and
new client credentials available through portal deploy/drain; do not delete the
old client while old portal processes can still use it.

### VM guest passwords (per-instance)

Range guest desktop / RDP passwords are unique per instance. They are
**not** stored in the platform secret bundles, **not** carried as
environment variables, and **not** baked into AMIs. The password value
**never appears in EC2 user_data, IMDS, Terraform-rendered cloud-init
manifests, or the guest's process argv**.

The lifecycle aligns with the documented best practice for AWS Systems
Manager Parameter Store + Run Command (and the GCP equivalent: control-
plane-pushes-after-boot via the per-instance SSH identity-brokered
channel). See `docs/_deprecated/architecture/vm-guest-credential-preflight-762.md`.

#### Lifecycle

1. **Generate**: the range Terraform module (AWS) and
   `gdc_vmruntime_assets._ensure_rdp_password_secret` (GCP) generate a
   per-instance random password with all four character classes (upper,
   lower, digit, shell-safe punctuation) enforced.
2. **Store**: the value is persisted in the cloud's secret manager:
   - AWS: `arn:aws:secretsmanager:<region>:<account>:secret:shifter/<env>/range/<range_id>/<role>-<uuid8>-rdp-password`
   - GCP: `projects/<project>/secrets/shifter-<env>-range-<range_id>-<role>-<token>-rdp-password`
3. **Reference, do not render**: the secret ARN / resource path flows
   into `engine_instance.state.rdp_password_secret_arn` and
   `Range.provisioned_instances[].rdp_password_secret_arn`. The
   *value* never lands in EC2 user_data, GDC VM Runtime
   cloud-init data, or Terraform-rendered scripts.
4. **Push at provisioning time**: after the instance comes up and the
   per-instance SSH key is in `authorized_keys` /
   `administrators_authorized_keys`, the engine provisioner runs
   `SetLocalPasswordPlan` via `SetupOrchestrator`:
   - Linux (kali, ubuntu): the password is piped through `chpasswd`
     stdin, never as a `chpasswd` argv.
   - Windows victim: `Set-LocalUser -Password (ConvertTo-SecureString …)`,
     never as a `net user` argv.
   - `SetupOrchestrator.SENSITIVE_CONTEXT_KEY_PARTS` masks the value
     in captured stdout/stderr because the context key is
     `rdp_password`.
5. **Resolve at access time**: the portal's
   `engine.services._resolve_non_dc_rdp_password` reads the per-
   instance secret reference from `Range.provisioned_instances` and
   fetches the value via `engine.secrets.get_rdp_password` →
   `shared.cloud.get_secrets_store().get_secret()`. A failed secret fetch raises a non-sensitive `ValueError`. The Mission Control RDP view maps it to HTTP 400, as with a missing reference.

#### RAES-authored account credentials

The RAES-native GCE path treats authored accounts separately from the
provisioner's `raes` management login and from portal/participant credentials.
For every enabled account on every concrete node instance, the provisioner
read-or-creates a deterministic Secret Manager entry keyed by range, instance,
username, and canonical `auth_method`:

- `password` generates according to the authored `weak`, `medium`, or `strong`
  policy and reuses `SetLocalPasswordPlan` to install and verify it.
- `publickey` stores the generated private key and sends only the public half to
  an account-specific `authorized_keys` path. Windows receives a `Match User`
  override so an administrator account never falls through to the shared
  `administrators_authorized_keys` file.
- Disabled accounts receive no usable credential. `password_strength: none` is
  accepted only for a disabled account, never as a blank-password login.

Credential values and references do not enter the serialized RAES plan, GCE
metadata, provisioner outputs, runtime snapshots, events, diagnostics, or logs.
The existing strict-host-key-checked management SSH channel carries setup after
boot, and `SetupOrchestrator` masks password context. Destroy reconstructs and
deletes each per-account secret. There is intentionally no portal or API
retrieval surface for these backend-owned credentials.

`auth_method` admits only the canonical `password` and `publickey` spellings at
both the shared admission boundary and the separate provisioner parser. The
backend does not declare RAES `mail`: Linux aliases and Windows marker files do
not provide one equivalent, verified mail-routing semantic.

#### DC role

The DC retains deployment-scoped `DC_DOMAIN_PASSWORD`. Its local Administrator is the domain Administrator. Rotation therefore follows DC promotion and image coordination, not the per-instance secret procedure.

#### Residual state exposure

Generated AWS `random_password.result` and GCP `add_secret_version` payloads enter process memory during apply. AWS passwords also enter Terraform state, like `tls_private_key.instance` and `aws_secretsmanager_secret_version.ssh_key`. State protection remains required.
Terraform state lives in the S3 backend with bucket-level encryption
and least-privilege IAM access; this is the established mitigation.
Eliminating state exposure entirely would require external secret
generation (for example, a Lambda invoking `aws secretsmanager create-secret`)
and is a separate workstream.

#### AWS delivery channel

After bootstrap, the provisioner reads the guest's ed25519 SSH host public key
over the authenticated SSM control channel. It pins the host key, then reads the instance password and management private key from Secrets Manager. Only pinned SSH stdin carries the password. The non-secret setup
script travels separately. The password therefore does not enter EC2 user data,
SSM Run Command history, script source, process argv, environment, or metadata.
The guest instance role has no permission to read the secret store.

Do not substitute `{{ssm-secure:...}}`. That is a CloudFormation dynamic reference. Run Command document parameters do not support SecureString Parameter Store references.

#### Rotation

Rotate per-instance credentials by destroying and re-provisioning through the range lifecycle. Terraform regenerates `random_password`, replaces the secret version, and `SetLocalPasswordPlan` installs it during provisioning. Image rebuilds (Packer) do **not** rotate
live credentials; they only refresh the bootstrap scripts shipped on
first boot.

### Domain Controller Administrator Password

The portal and provisioner entrypoints hydrate the referenced password at startup.
Updating Secret Manager does not refresh a running process.
Current range provisioning uses Kubernetes Jobs; retired ECS injection and EC2 restart instructions do not apply.

Before rotation, confirm the selected portal root, secret reference, DC image, and all live range dependencies.
Obtain the platform and range owners' approval for the maintenance window.
A prebaked DC image and its runtime secret must use the same domain Administrator password.

1. In the selected portal root, save a private plan that replaces `random_password.dc_domain_password`:

   ```bash
   umask 077
   ROTATION_PLAN=/absolute/private/directory/rotation.tfplan
   terraform plan -replace='random_password.dc_domain_password' -out="$ROTATION_PLAN"
   ```

2. Review and apply that exact plan through the authorized infrastructure procedure.
   The plan contains secret values. Restrict its access and remove it after the approved retention period.
3. Redeploy the application through the EKS lifecycle to refresh long-running consumers.
4. Rebuild or replace the DC image as required to match the new credential.
5. Re-provision affected ranges through their lifecycle service and verify domain join and cleanup.

Retain prior secret versions and image identities until recovery is verified.
Restoring only the secret does not restore a DC that already changed its password.
Do not print values, restart arbitrary containers, or terminate an EC2 instance to refresh an EKS deployment.

### GitHub OIDC Role
Role ARN does not change. Trust policy updates are in `platform/terraform/global/iam/`.

### GCP Workload Identity Federation
The provider resource and target service account stay stable. Rotate or tighten
permissions in GCP IAM without changing the GitHub workflow contract unless the
provider or service account identity itself changes.

Federation is optional (ADR-070). A GCP deployment that runs without GitHub
grants `roles/iam.serviceAccountTokenCreator` on each purpose identity only to
the principals in the `impersonation_principals` input of the `cicd-oidc` root.
Change that list to add or remove an operator. No service-account key exists.

## Accessing Secrets Locally

For local development, you can retrieve secrets:

```bash
# Get a secret value
aws secretsmanager get-secret-value \
  --secret-id shifter-dev-portal-db-credentials \
  --profile $PANW_SHIFTER_DEV_PROFILE \
  --query SecretString --output text | jq .

# Use in environment
export DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id shifter-dev-portal-db-credentials \
  --profile $PANW_SHIFTER_DEV_PROFILE \
  --query SecretString --output text | jq -r .password)
```

## Security Checklist

- [ ] Secret not in any committed file
- [ ] Secret not in shell history (`use read -s` for input)
- [ ] Appropriate IAM policy restricts access
- [ ] Rotation procedure documented
- [ ] Dev and prod use different secrets
