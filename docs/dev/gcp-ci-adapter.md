# Retained GCP CI deploy adapter

Part of the BigRAE deploy and operations docs; start at the [documentation home](../index.md).

This page collects the reference for the retained GitHub CI adapter of GCP
deployments, `.github/workflows/_gcp-dev.yml`.
It is not a selectable installation path.

No tenant uses the CI path after #2668. `deploy.yml` offers no GCP environment
until a tenant is wired in, and #2672 decides the future of this path.

To install from a release, use [Install on Google Cloud](../getting-started/install-gcp.md).
The [GCP deployment handbook](../technical/handbook/gcp-github-less-deployment.md)
describes the commands that the adapter runs. Each CI job renders the
deployment input bundle from the GitHub secrets and variables, then runs the
same command as its federated purpose identity (`--identity ambient`).

## Prerequisites

- A GCP project with billing enabled, and every Vertex AI model that the
  configuration uses enabled.
- The foundation, applied with `deploy.py gcp-foundation`: Workload Identity
  Federation for GitHub Actions (pool, provider, purpose service accounts),
  with the explicit `GCP_*_SERVICE_ACCOUNT` value and
  `GCP_WORKLOAD_IDENTITY_PROVIDER` set in each purpose Environment.
- A release that selects the Kali, Ubuntu, and DC guest images. `deploy.py
  gcp-images` verifies and imports them as native GCE images; no
  platform-owned transfer bucket must already exist. See
  [`gcp-range-cell-deploy.md`](gcp-range-cell-deploy.md) and
  [`gcp-guest-images.md`](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/gcp-guest-images.md).

## Foundation for CI

For a CI deployment, copy `scripts/bootstrap/gcp-foundation.example.tfvars.json` to an
operator-owned file outside the repository. Supply the project ID and number,
numeric GitHub repository and owner IDs, bucket names, and exact purpose
Environment/branch/workflow tuples. Obtain IDs with `gcloud projects describe`
and `gh api repos/<owner>/<repo>`; bootstrap verifies them before writes.

Deploy uses the selected tenant branch. A destroy tuple must bind protected
`refs/heads/dev` or `refs/heads/main`; bootstrap rejects any other destroy tuple
before writes. No GitHub workflow uses a destroy identity after #2668.

Follow the staged cutover and readback in
[GitHub Actions WIF trust](deploy-secrets.md#github-actions-wif-trust-adr-004-r23).
Add each output only to its matching GitHub Environment:

| Secret | Value |
|--------|-------|
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy service account email |
| `GCP_RELEASE_SCAN_SERVICE_ACCOUNT` | Release-scan service account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |

Instead of `foundation-inputs.json` in the bundle, a CI deployment sets the
tenant Environment variable `GCP_FOUNDATION_INPUTS_JSON`, then manually dispatches **Deploy** from
that tenant branch with its matching `environment` and
`gcp_reconcile_foundation_image_network=true`. The stage then runs as the
[bootstrap README](../../scripts/bootstrap/README.md#fresh-gcp-account-order) describes.

## Stand up a CI deployment

Configure and review an explicit authorized target before any dispatch.
No GCP target currently exists in `deploy.yml`.

1. Create the GCP project and enable the required APIs.
2. Apply `platform/terraform/gcp/global/cicd-oidc`. It creates the GitHub Workload Identity pool/provider and purpose-scoped CI identities. Apply
   selected deployment values in each project. Each project keeps its own state bucket/prefix. Then set each
   purpose Environment's explicit service-account secret and
   `GCP_WORKLOAD_IDENTITY_PROVIDER` from the applicable profile outputs. Its state prefix is separate from platform state. Platform destruction therefore retains CI authentication resources, as with `global/github-runner`:

   ```bash
   cd platform/terraform/gcp/global/cicd-oidc
   REPO="$(gh repo set-default --view)"   # Empty: run gh repo set-default <owner>/<repo> first.
   mapfile -t GITHUB_IDS < <(gh api "repos/$REPO" --jq '.id, .owner.id')
   terraform init -backend-config="bucket=<project-id>-terraform-state" -backend-config="prefix=cicd-oidc"
   terraform apply -var="project_id=<project-id>" -var="project_number=<project-number>" \
     -var="environment=<environment>" -var="name_prefix=<name-prefix>" \
     -var="github_org=${REPO%/*}" -var="github_repo=${REPO#*/}" \
     -var="github_repository_id=${GITHUB_IDS[0]}" -var="github_owner_id=${GITHUB_IDS[1]}" \
     -var="terraform_state_bucket_name=<project-id>-terraform-state" \
     -var="release_evidence_bucket_name=<release-evidence-bucket>" \
     -var-file=/path/to/purpose-contexts.tfvars.json \
     -var='platform_external_bucket_names=["<raes-package-bucket>","<ctf-content-bucket>"]'
   terraform output -raw workload_identity_provider          # GCP_WORKLOAD_IDENTITY_PROVIDER
   terraform output -raw release_scan_service_account_email     # GCP_RELEASE_SCAN_SERVICE_ACCOUNT
   terraform output -raw deploy_service_account_email           # GCP_DEPLOY_SERVICE_ACCOUNT
   terraform output -raw release_evidence_bucket_name           # private raw evidence store
   ```
   `purpose-contexts.tfvars.json` holds only the `purpose_contexts` key, in
   the shape of `gcp-foundation.example.tfvars.json`.
   Omit empty optional bucket entries. The external bucket set must exactly cover non-empty `raes_package_bucket_name` and `ctf_content_bucket_name` inputs. This permits workload IAM management on those buckets without project-wide Storage Admin.
   Publish each purpose output only to its matching protected Environment. For existing installations, follow the staged identity cutover and state-address readback in [GitHub Actions WIF trust](deploy-secrets.md#github-actions-wif-trust-adr-004-r23). Do not directly replace the shared CI principal.
3. Configure the GCP deployment secrets and variables in
   [GitHub secrets and variables](#github-secrets-and-variables), including
   `SHIFTER_CONFIG_GCP_DEV` and the
   [GCE range-cell variables](gcp-range-cell-deploy.md#gce-range-cell-settings).
4. Import the guest images that the release selects and print their exact
   references:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-images \
     --project-id <project> --region <region> \
     --release-manifest <release.json> --trusted-repository-id <id> --trusted-owner-id <id>
   ```

   Set the printed references as the `GCP_RANGE_LINUX_IMAGE`,
   `GCP_RANGE_KALI_IMAGE`, and `GCP_RANGE_DC_IMAGE` variables. A deployment
   without GitHub passes `--store gs://<bucket>` instead. The command then reads
   the trust from the store and writes `range-images.json`. Without
   `--release-manifest`, it reads the release manifest of the deployer image. The
   command verifies the signed build provenance of all three images before it
   changes anything. Missing images transfer through a private per-run bucket in the selected project and region. Success and failure both remove that bucket and every transfer object. Required native GCE images must report `READY`. A retry reuses matching `READY` images and creates no bucket when no
   import is necessary. Add `--dry-run` to verify and inspect without pulling
   disk payloads or mutating GCP.

   A developer build of `packer-gcp.yml` publishes a guest image only after
   `packer-gcp-validate.yml` passes for the exact candidate. See
   `docs/dev/gcp-range-cell-deploy.md` and
   `docs/architecture/gcp-guest-images.md`.
5. Run the first deploy through CI as a manual dispatch with
   `gcp_require_active_certificate=false`:
   `gh workflow run deploy.yml --ref <branch> -f environment=<environment> -f gcp_require_active_certificate=false`.
   The CI adapter renders the deployment input bundle from the GitHub values,
   and the jobs run `gcp-deploy`, `gcp-release-scan`, and `gcp-smoke`. Deployment applies GCP Terraform for GKE, Cloud SQL, Memorystore, and Pub/Sub. The CI adapter builds and attests control-plane images. Migration and catalog stages precede final workload readiness.
6. Subsequent deploys run through CI as a manual dispatch:
   `gh workflow run deploy.yml --ref <branch> -f environment=<environment>` (see
   the CI/CD trigger matrix in `docs/technical/dev/ci-cd.md`). Branch names no
   longer trigger deploys.
7. Point the configured hostname at the reserved global ingress IP so the
   Google-managed TLS certificate can activate.

The control-plane images that the CI adapter builds go to the deployment
Artifact Registry. A deployment without GitHub copies the release images there.

## Add a GCP CI deployment

A future GCP CI deployment needs these reviewed repository changes:

1. Add its value file under `gcp/environments/<environment>/`.
2. Configure its protected GitHub Environments and purpose identities.
3. Add its explicit workflow authorization choice.
4. Use a separate state bucket/prefix.

Do not copy the shared Terraform source.
See [deployment configuration and recovery](deployment-configuration.md).

## GitHub secrets and variables

Consumed by `.github/workflows/_gcp-dev.yml` for a GCP CI deployment. The CI
adapter (`scripts/gcp/render_ci_deployment_inputs.py`) projects each value onto
its home in the deployment input bundle. Then the jobs run `gcp-deploy`,
`gcp-release-scan`, and `gcp-smoke`. A GitHub value that conflicts with a value
in `SHIFTER_CONFIG_GCP_DEV` stops the render, so each input keeps one meaning.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `GCP_PROJECT_ID` | secret | yes | The Google Cloud project the platform deploys to. |
| `SHIFTER_CONFIG_GCP_DEV` | secret | yes | Full validated deployment `bigrae.yaml`. The CI adapter writes it as the bundle's `bigrae.yaml`. It is the sole source of `dynamic_secret_project_id`, exact provisioner static-secret refs, and range egress policy for deploy and destroy. |
| `GCP_REGION` | variable | no | Projected onto `settings.region`. Default `us-central1` when neither sets it. |
| `GCP_PUBLIC_HOSTNAME` | secret | yes | DNS name the platform serves on (for example, `shifter.your-domain.example`). Projected onto `deployment.domain`. |
| `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN` | secret | yes | Identity Platform beforeCreate allow-list; the bootstrap operator must end with `@<this>` for sign-in to succeed. The CI adapter writes it to the bundle's `terraform.tfvars.json`, with `gke_master_authorized_cidrs = []` for the Connect Gateway path. |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | secret | yes | Purpose-scoped WIF service account for deploy and post-deploy smoke. |
| `GCP_RELEASE_SCAN_SERVICE_ACCOUNT` | secret | yes | Purpose-scoped WIF service account for the isolated exact-digest image scan. Store it only in `gcp-release-scan-dev`; it has repository-scoped Artifact Registry read and create-only access under the private bucket's `release-scans/` prefix, but no deployment or runtime-secret authority. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | yes | Workload identity provider resource id. |
| `GCP_BOOTSTRAP_ADMIN_EMAIL` | secret | yes | Optional Identity Platform account seed; this does not grant application permission. Must match `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN`. Projected onto `settings.operator_bootstrap.admin_email`. Required unless `SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true` is set to deliberately skip operator creation (the skip is logged; it sets `operator_bootstrap.enabled: false`). |
| `GCP_BOOTSTRAP_ADMIN_PASSWORD` | secret | yes | Initial password for the provider account seed; native application access still requires immutable bootstrap facts. The infrastructure stage reads it from this variable (`--operator-password-env`); it is never written to the bundle. Required unless `SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true`. |
| `GCP_CTF_CONTENT_BUCKET` | variable | with content refs | GCS bucket holding digest-pinned native CTF content bundles; projected onto `settings.ctf_content_bucket`, rendered into the `ctf_content_bucket_name` tfvar, and surfaced to the runtime as `SHIFTER_CTF_CONTENT_BUCKET`. **Required when the app bundle has `ctf_content_references`:** `config/_ctf_content_settings.py` rejects references without a bucket. Missing binding prevents portal startup. The reference catalog itself stays in the app secret, never here. |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | secret | no | Legacy staff-email input; Django flags do not grant native application authority. Projected onto `settings.operator_bootstrap.staff_emails`. |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | secret | no | Legacy superuser-email input; Django flags do not grant native application authority. Projected onto `settings.operator_bootstrap.superuser_emails`. |
| `SMOKE_TEST_USER_EMAIL` | secret | no | Post-deploy smoke user for the advisory `post-deploy-smoke` job. Projected onto `settings.post_deploy_smoke.user_email`. The CI smoke step fails and opens the smoke issue when it is empty. Same contract as AWS dev smoke; see [Post-deploy smoke secrets](deploy-secrets.md#post-deploy-smoke-secrets-dev). |
| `IDENTITY_CUTOVER_FACTS_JSON` | secret | first hard cut | Reviewed `shifter.identity-cutover-facts/v1` mapping document. CI writes a temporary owner-only file and passes its path as `--identity-cutover-facts`; the command mounts facts only into the one-shot cutover Job and cleans up afterward. |
| `IDENTITY_BOOTSTRAP_FACTS_JSON` | secret | first hard cut | `shifter.identity-bootstrap-facts/v1` names the exact immutable provider issuer and subject for the first native administrator. CI passes an owner-only file path as `--identity-bootstrap-facts`. Email lookup is not accepted. Both fact files are required together for the first cutover. |
| `CATALOG_CREDENTIAL` | secret | catalog setup | Current native bearer proof with installation content registration, conformance and publication authority. CI writes a temporary `0600` file, passes only its path as `--catalog-credential-file`, clears the environment value before the command and removes the file afterward. It never enters the deployment bundle. Missing proof leaves the activated application available but reports catalog setup incomplete; obtain a current credential after activation and retry. |

The prepare job scopes its shared preflight to the deployment Environment. The
exact-release scanner validates `GCP_RELEASE_SCAN_SERVICE_ACCOUNT` and its WIF
provider inside the separate `gcp-release-scan-<deployment>` Environment, so
the scanner identity never has to be copied into the deploy Environment.

No GitHub workflow tears down a GCP deployment after #2668. An operator runs
`deploy.py gcp-destroy` as the destroy identity (see the
[GitHub-less GCP deployment guide](../technical/handbook/gcp-github-less-deployment.md)).


`SHIFTER_CONFIG_GCP_DEV` is also required by both deploy and destroy. Its GCP
settings must include `dynamic_secret_project_id`; no separate GitHub variable
or tfvars override owns that value. The project is a pre-existing,
single-deployment Secret Manager boundary and may equal `project_id` only during
the documented expand phase. Once cut over it must be distinct.

Supported operator-created inputs are declared once in the same config:

```yaml
settings:
  project_id: platform-project
  dynamic_secret_project_id: range-secret-project
  provisioner_static_secret_refs:
    GDC_ACCESS_SECRET_ID: projects/platform-project/secrets/shifter-gcp-dev-gdc-access
    GDC_VM_IMAGE_GCS_SECRET_ID: projects/platform-project/secrets/shifter-gcp-dev-gdc-vm-image-gcs
    GDC_VMSERIES_IMAGE_GCS_SECRET_ID: projects/platform-project/secrets/shifter-gcp-dev-gdc-vm-image-gcs
```

Omit unused keys. Values are secret references, never payloads, and must identify
existing resources before Terraform applies. This closed map supplies exact provisioner IAM and runtime publication. Do not duplicate references in `local.auto.tfvars` or an ad hoc runtime overlay. See the
[range-secret project rollout](https://github.com/OpenRAE/bigrae/blob/dev/platform/terraform/gcp/README.md#expand-cut-over-drain-contract).

Native CTF scenario-content references live in the existing application secret,
not in GitHub variables or the generated ConfigMap. Configure the private
bucket through the GCP Terraform input and follow the
[native CTF scenario-content runbook](ctf-scenario-content.md).

`gcp-deploy` validates the bootstrap operator email against the Terraform output
`identity_allowed_email_domain` before it creates the operator.

### Range egress payload

`gcp-deploy` renders the range egress variables from `SHIFTER_CONFIG_GCP_DEV`
before `terraform apply`. The render fails loud when the secret is empty. See
[Range egress allowlist](gcp-range-cell-deploy.md#range-egress-allowlist).

## Value files and state selection

The retained CI adapter expects values under `environments/<environment>/terraform.tfvars`.
Current source retains no selectable GCP CI deployment or environment value directory.
The CI adapter copies that file into the bundle and adds the GitHub secret values in `terraform.tfvars.json`.

The following is retained contributor state-selection syntax, not a current selectable CI deployment.
Restore the authorized value source and private overrides before using it:

```bash
environment=gcp-dev
values_dir="$PWD/platform/terraform/gcp/environments/$environment"
export TF_DATA_DIR="$values_dir/.terraform"
root=platform/terraform/gcp/environments/platform

terraform -chdir="$root" init -reconfigure \
  -backend-config="bucket=<existing-state-bucket>" \
  -backend-config="prefix=shifter/$environment/platform-core"

terraform -chdir="$root" plan \
  -var-file="$values_dir/terraform.tfvars" \
  -var-file="$values_dir/local.auto.tfvars"
```

Supply every operator override that the environment previously used.
Keep generated range settings last when they are part of the deployment.
Pass the same files to apply, import and destroy.
Never share `TF_DATA_DIR` between environments.
Do not put environment values or credentials in the shared root.

## Retained `gcp-dev` values

- Project: `example-gcp-project`
- Hostname: `shifter.example.com`
- Managed TLS: enabled
- Authorized admin CIDRs: empty; operator and CI access use Connect Gateway
