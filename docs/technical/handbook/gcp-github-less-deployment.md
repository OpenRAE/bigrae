# GitHub-less GCP deployment

Applicability: GCP deployments that use the GitHub-less deploy path (ADR-070).
Operator: platform owner. Source reviewed: 2026-11-09 at revision `5954ab137`.
This review did not execute a live deployment.

Use these how-to procedures to install, update, and remove a GCP deployment from a verified release.
Start a new installation with [Install on Google Cloud](../../getting-started/install-gcp.md).
The deployment needs no GitHub access, GitHub Environment, self-hosted runner, or repository checkout.
The deployer image contains `scripts/bootstrap/deploy.py` and the release's tools.

Releases through v4.1.1 do not contain the deployer image.
Use a later approved release that contains it.
See the [deployment compatibility reference](../platform_infrastructure/deployment-compatibility.md) for source, release, and contributor-path limits.

An operator installs with one bundle and one command, `gcp-install`
([Install](#install)), and updates with `gcp-deploy`
([Update and roll back](#update-and-roll-back)).

The retained CI adapter (`_gcp-dev.yml`) uses the same commands.
`deploy.yml` currently has no selectable GCP target.
Contributor GitHub inputs are in [deploy-secrets.md](../../dev/deploy-secrets.md#gcp-gcp-dev).
When a command fails, use [RB023](../../runbooks/rb023-gcp-deployment.md).

## Terms

| Term | Meaning |
| --- | --- |
| Release | One source revision: five control-plane images, one deployer image, and their attestations in the release registry. |
| Release registry | The public registry `ghcr.io/<owner>/<repository>` that `release-gcp.yml` writes and every deployment reads. |
| Mirror | A registry that an operator fills with the release images by digest, for a deployment that cannot reach the release registry. |
| Release manifest | `bigrae.gcp-release.v1` JSON with the source revision, the chart version, the exact image digests, the pinned base range images, and the authorization model. The deployer image holds it at `/opt/bigrae/release.json`. |
| Deployer image | The container that holds the commands, the Terraform roots, the Helm chart, and the pinned tools of one release. |
| Deployment input bundle | The objects that one deployment reads: `bigrae.yaml`, the Terraform values, and the range image references. |
| Deployment config bucket | The GCS bucket that holds the deployment input bundle and the deployment lock. |
| Purpose identity | One of the deploy, release-scan, and destroy service accounts of a deployment. |

## Prerequisites and roles

1. Make sure that the GCP project exists and that billing is on.
2. Enable every Vertex AI model that the deployment configuration uses. The
   Vertex AI API alone does not enable a model.
3. Make sure that your Google identity can administer the project IAM:
   `roles/owner`, or `roles/resourcemanager.projectIamAdmin`,
   `roles/iam.roleAdmin`, and `roles/iam.serviceAccountAdmin`. `gcp-install`
   applies the foundation and names your identity in
   `impersonation_principals` for `deploy`, `release_scan`, and `destroy`. The
   foundation gives each listed principal
   `roles/iam.serviceAccountTokenCreator` on that purpose identity only.
4. Make sure that you can pull from the release registry. It is public. A
   deployment that cannot reach it uses a mirror
   ([Deploy from a mirror](#deploy-from-a-mirror)).
5. Sign in to Google Cloud. The commands use your credentials only to
   impersonate the purpose identities.

   ```bash
   gcloud auth login <operator-email> --no-activate
   gcloud auth application-default login <operator-email>
   ```

6. Use the deployer image of the release
   ([Get and verify the deployer image](#get-and-verify-the-deployer-image)).
   The image holds every tool at the release version.
7. If you run the commands from a checkout instead, check out the exact release
   revision with no local changes. Install these tools on `PATH`: `gcloud`,
   `gke-gcloud-auth-plugin`, `terraform`, `kubectl`, `helm`, `oras`, `trivy`,
   `git`, and `uv`. The command stops when a tool is missing.
8. From a checkout, run each command through the `scripts/bootstrap` uv
   project. The project holds the Python dependencies of the commands. In this
   guide, `./scripts/bootstrap/deploy.py` means:

   ```bash
   uv run --project scripts/bootstrap scripts/bootstrap/deploy.py <command>
   ```

The foundation needs project administration rights. `gcp-images` runs as your
own identity: it creates Compute Engine images and a temporary transfer bucket
in the project.

Pin the operator with `CLOUDSDK_CORE_ACCOUNT` in each command or container environment.
Application Default Credentials replace the host's existing ADC when you sign in.
Confirm project administration, DNS authority, quota, billing, and the maintenance window before making changes.
Installation creates billable compute, databases, networking, storage, and images.
The evidence bucket has locked 90-day retention; its objects cannot be removed before retention ends.

## Publish a release

The repository maintainer does this procedure once for each release. A
deployment operator only consumes the result. One release serves every
deployment, and a new deployment needs no change here.

1. Create the `gcp-release` GitHub Environment once. Limit it to the release
   refs `refs/heads/main`, `refs/heads/dev`, and `refs/heads/deploy-test`.
   Protect each of these branches. The Environment holds no secrets or
   variables.
2. Merge the Release Please release PR on `main`. The `release-gcp` job of
   `release-please.yml` then builds the release for the tagged commit (#2660).
   To build a test release from `dev` or `deploy-test`, or to publish a release
   again, dispatch the workflow. The `version` input is optional; an empty value
   uses `version.txt`.

   ```bash
   gh workflow run release-gcp.yml --ref dev
   ```

3. Read the deployer image digest and the release manifest in the run summary.
4. After the first release only, make each package public in the GitHub
   package settings: `portal`, `provisioner`, `guacd`, `guacamole-client`,
   `openvpn`, and `deployer-gcp`. GHCR makes a new package private.

The workflow publishes to `ghcr.io/<owner>/<repository>`, in lower case, with
the workflow `GITHUB_TOKEN`. It uses no cloud identity.

The workflow scans the deployer image digest before it attests the image. The
scan is a blocking Trivy gate: `trivy image --scanners vuln --severity
HIGH,CRITICAL --ignore-unfixed --exit-code 1`. Trivy reads its vulnerability
databases from `mirror.gcr.io`. A HIGH or CRITICAL finding with a fix stops the
release.

The only accepted exposures are in `platform/deployer/gcp/trivyignore.yaml`.
Each entry is a HIGH finding in a vendor binary that no vendor build fixes yet.
Each entry expires on 2026-11-30. After that date, the gate blocks each release
until a maintainer updates the tools.

A developer builds the guest images in a build project and publishes them to
`ghcr.io/<owner>/<repository>/gce-<role>` with signed provenance. Each release
names the newest publication of each role whose provenance verifies, and the
release manifest carries the authorization model that each deploy publishes. A
release stops when a guest image is missing or does not verify. The
[guest image design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/gcp-guest-images.md) describes the build
project and the pipeline.

## Get and verify the deployer image

1. Set the release registry and the release revision:

   ```bash
   REG=ghcr.io/<owner>/<repository>
   REV=<40-hex revision>
   ```

2. Resolve the deployer image digest:

   ```bash
   DIGEST=$(oras resolve "$REG/deployer-gcp:$REV")
   ```

3. Verify the build provenance of the deployer image. Set `<release ref>` to
   `refs/heads/main` for a tagged release, or to the branch of a test release:

   ```bash
   cosign verify-attestation --type https://slsa.dev/provenance/v1 \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/release-gcp.yml@<release ref>" \
     --certificate-github-workflow-sha "$REV" "$REG/deployer-gcp@$DIGEST"
   ```

4. Read the release manifest:

   ```bash
   docker run --rm --entrypoint cat "$REG/deployer-gcp@$DIGEST" /opt/bigrae/release.json
   ```

5. Run each command in this guide through the deployer image. Always use the
   digest, not the tag:

   ```bash
   docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp \
     -e CLOUDSDK_CONFIG=/gcloud \
     -e GOOGLE_APPLICATION_CREDENTIALS=/gcloud/application_default_credentials.json \
     -v "$HOME/.config/gcloud:/gcloud" \
     "$REG/deployer-gcp@$DIGEST" gcp-deploy --store gs://<bucket>
   ```

The deployer image sets `BIGRAE_RELEASE_MANIFEST` and
`BIGRAE_SOURCE_REVISION`. The command uses that manifest by default. It also
checks that its own revision equals the manifest revision. A checkout must be a
clean checkout of that revision; otherwise the command stops.

A test deployment can run deploy tooling that is not the release revision
(#2689). Use this to test a deploy-script change without a new release build.

1. Set `deployment_tier: test` in the `settings` block of `bigrae.yaml`.
2. Commit the change to the tooling. The command refuses local changes.
3. Run `gcp-deploy` from that checkout with `--allow-unreleased-tooling`.

The command refuses the flag for a production deployment and for a CI run
(`--identity ambient`). Before any change, it stores `tooling-override.json`
in the release-evidence bucket, under
`deployments/<release-revision>/<run-id>/<attempt>/`. The record holds the
release revision and the tooling revision. The release images still get the
same provenance check and scan.

`gcp-deploy` verifies the provenance of the five control-plane images before
the rollout. That check binds each image to the repository ID, the owner ID,
and the revision in `settings.release_trust` and the manifest. It then copies
each image by digest into the deployment's own Artifact Registry. The commands
send your Google credentials only to Artifact Registry, never to the release
registry.

## Deploy from a mirror

Use a mirror when the deployment cannot reach the release registry.

1. On a host that can reach both registries, copy each release image of the
   manifest to the mirror. Keep the digest and the referrers:

   ```bash
   for name in portal provisioner guacd guacamole-client openvpn; do
     SRC=$(jq -r --arg n "$name" '.images[$n]' release.json)
     oras cp --recursive "$SRC" "<mirror>/$name:release-${REV:0:12}"
   done
   ```

2. Copy the deployer image the same way to `<mirror>/deployer-gcp`.
3. Pass the mirror prefix to each command:

   ```bash
   gcp-deploy --store gs://<bucket> --release-source <mirror>
   ```

`gcp-deploy`, `gcp-destroy`, and `gcp-release-scan` accept `--release-source`.
They read each image at `<mirror>/<name>@<release digest>`. The provenance
check verifies the same digests, so a mirror cannot change the release.

## Install

1. Write the deployment input bundle in a private directory
   ([Author and publish the deployment input bundle](#author-and-publish-the-deployment-input-bundle),
   steps 1 to 4). It is the only configuration of the deployment.
2. Run the install from the deployer image of the release. Mount the bundle
   directory into the container, for example with
   `-v /path/to/bundle:/bundle:ro`, and pass `--inputs /bundle`:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-install --inputs /path/to/bundle
   ```

3. Read the ingress address in the command output.
4. Create a DNS A record for `deployment.domain` at that address. Do not proxy
   the record.
5. Run the deploy. It waits up to 60 minutes for the managed certificate to
   become Active, then runs the smoke:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-deploy --store gs://<project>-deployment-config
   ```

`gcp-install` does these steps. Each step is idempotent, so run the same
command again after a failure:

1. It validates the bundle.
2. It applies the foundation without GitHub. It derives the inputs from the
   bundle and names your active gcloud account as the only impersonation
   principal. Pass `--operator` to name another principal.
3. It creates the initial operator password secret when it does not exist, and
   prints the command that reads it.
4. It publishes the bundle to `gs://<project>-deployment-config`.
5. It waits until your identity can read that bucket as the deploy identity.
   IAM can take several minutes to apply the new foundation grants. The
   command stops after 10 minutes.
6. It runs `gcp-deploy --first-install`. On a new deployment, that deploy:
   - imports the base range images that the release pins, as your identity;
   - generates the OpenFGA CA, server certificates, and keys into Secret
     Manager;
   - publishes the release's authorization model to OpenFGA;
   - creates the first administrator from
     `settings.operator_bootstrap.admin_email`;
   - registers the in-box catalog as that administrator.

The sections that follow describe each part, for a manual install and for
later changes.

## Apply the foundation without GitHub

1. Copy `scripts/bootstrap/gcp-foundation.github-less.example.tfvars.json` to a
   file outside the repository.
2. Set these keys:

   | Key | Value |
   | --- | --- |
   | `project_id`, `project_number` | The deployment project. The command compares the number with the project. |
   | `environment` | The deployment name. Use the same value as `deployment.name` in `bigrae.yaml`. |
   | `name_prefix` | `shifter-<environment>`. The commands derive the purpose identities from it. |
   | `impersonation_principals` | `deploy`, `release_scan`, and `destroy`, each with at least one `user:`, `group:`, or `serviceAccount:` member. |
   | `deployment_config_bucket_name` | The config bucket, for example `<project>-deployment-config`. |
   | `terraform_state_bucket_name` | `<project>-terraform-state`. The deploy command uses this name, and the foundation rejects any other name. |
   | `release_evidence_bucket_name` | `<project>-release-evidence`. The deploy command uses this name, and the foundation rejects any other name. |
   | `region` | The bucket location, for example `us-central1`. |

3. Do not set `purpose_contexts`, `github_org`, `github_repo`,
   `github_repository_id`, or `github_owner_id`. The command rejects GitHub
   inputs in this mode.
4. Preview the foundation:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-foundation --inputs /path/to/foundation.json --dry-run
   ```

5. Apply the foundation:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-foundation --inputs /path/to/foundation.json --yes
   ```

The command enables the foundation APIs and creates the private, versioned
state bucket. It then applies `platform/terraform/gcp/global/cicd-oidc` from a
saved plan. That root creates no Workload Identity pool or provider in this
mode. It creates these resources:

- the deploy, release-scan, and destroy service accounts;
- the token-creator grants for the named principals;
- object and bucket-owner grants on the state bucket for the deploy principals.
  Each deploy removes the broad project bindings from the state bucket, so
  these grants keep the operators' access to the foundation state;
- the release-evidence bucket, with a locked 90-day retention policy;
- the deployment config bucket, with uniform access, public access
  prevention, and versioning;
- the `<name_prefix>-foundation-gcs` key ring, with one customer-managed key
  for each foundation bucket
  ([Bucket encryption keys](#bucket-encryption-keys));
- custom Cloud KMS roles for the deploy and destroy identities. These roles
  can not destroy, disable, or delete a key or a key version;
- Cloud Audit Logs for storage reads and writes in the project. Usage-log
  delivery to the release-evidence bucket is optional
  (`enable_gcs_usage_log_delivery`), because a Domain Restricted Sharing org
  policy rejects its Google-managed writer group;
- the image-build network and the image build service account, only when
  `enable_image_build_network` is `true`.

After the apply, the command rewrites the live objects of each foundation
bucket with the bucket key. It does not rewrite the release-evidence bucket,
because its retention policy is locked.

The retention lock on the release-evidence bucket is permanent. Check the
project and the bucket name in the plan before you apply it.

The deploy and destroy identities can read the config bucket. They can change
only the `locks/` prefix. Deploy principals can write the bundle; destroy-only
principals can read it.

## Create the initial secrets

Platform Terraform creates and fills the Django, database, Guacamole, Redis, and domain-controller runtime secrets. The deploy generates the OpenFGA credentials.
`gcp-install` creates the first operator password in
`shifter-<environment>-operator-password` when
`settings.operator_bootstrap.admin_password_secret_ref` is not set. To supply
your own password instead, create the secret first:

1. Create the secret in the deployment project:

   ```bash
   gcloud secrets create <operator-password-secret> \
     --project <project> --replication-policy=automatic
   ```

2. Add the password as a new version. Do not type it on the command line:

   ```bash
   read -rs OPERATOR_PASSWORD
   printf '%s' "$OPERATOR_PASSWORD" | gcloud secrets versions add <operator-password-secret> \
     --project <project> --data-file=-
   unset OPERATOR_PASSWORD
   ```

3. Set `settings.operator_bootstrap.admin_password_secret_ref` to the
   versionless resource `projects/<project>/secrets/<operator-password-secret>`.
   The command reads the `latest` version as the deploy identity.

The deploy identity holds the Secret Manager role in the deployment project.
Thus it can read a secret in that project. The command keeps the password in
memory only.

Other inputs that refer to secrets:

- If you set `email_backend` in the Terraform values, Terraform creates an
  empty `shifter-<environment>-email` secret. Add the provider API key to it.
- `settings.provisioner_static_secret_refs` applies only to the `gdc` range
  backend.
- `secrets.django_secret_key` in `bigrae.yaml` is a reference that the GCP
  backend schema requires.

## Author and publish the deployment input bundle

1. Create a private directory for the bundle.
2. Write `bigrae.yaml`:

   ```yaml
   version: 1
   backend: gcp
   deployment:
     name: <environment>
     domain: portal.<your-domain>
     profile: prod
   secrets:
     django_secret_key: prompt
   settings:
     project_id: <project>
     region: us-central1
     dynamic_secret_project_id: <range-secret-project>
     range_cells:
       zone: us-central1-a
     participant_openvpn:
       enabled: false
     operator_bootstrap:
       admin_email: <operator>@<your-domain>
     post_deploy_smoke:
       user_email: <smoke-account>@<your-domain>
     release_trust:
       github_repository_id: "<repository-id>"
       github_owner_id: "<owner-id>"
   ```

   | Setting | Meaning |
   | --- | --- |
   | `range_cells` | `backend` (`gce` or `gdc`), `zone`, `zones`, `project_id`, `host_identity_pool_size`, `private_google_access`, `image_key_profiles`, and `worker_vcpu`. A GCE range needs `zone`. `worker_vcpu` (default 8) is the vCPU draw of one disposable worker. |
   | `participant_openvpn.enabled` | Deploys the shared participant OpenVPN pool. The default is `false`. |
   | `ctf_content_bucket` | The private CTF content bucket, when the app secret carries CTF content references. |
   | `operator_bootstrap` | The first operator and the first administrator. `gcp-deploy` requires this block. `enabled` defaults to `true` and then requires `admin_email`. `admin_password_secret_ref` defaults to the secret that `gcp-install` creates. |
   | `openfga` | Optional override block. The deploy always configures OpenFGA. Leave unset for generated credentials and the release model. For overrides, set all three `*_secret_ref` values; `store_id` and `model_id` are optional. |
   | `cloud_sql_iam_auth` | Native SQL login. It defaults to `true`, which the current source requires. |
   | `post_deploy_smoke.user_email` | The portal account that owns the smoke range. The smoke creates the account when it does not exist. An empty value skips the smoke. |
   | `release_trust` | The numeric repository ID and owner ID of the repository that publishes the release. |
   | `deployment_tier` | `production` (the default) or `test`. Only a `test` deployment accepts `gcp-deploy --allow-unreleased-tooling`. |

   The operator email must use the domain in `identity_allowed_email_domain`.
   For a release from `OpenRAE/bigrae`, the release trust IDs are
   `github_repository_id: "1241599684"` and `github_owner_id: "308592074"`.
   For a release from another repository, run
   `gh api repos/<owner>/<repo> --jq '.id, .owner.id'` once on any workstation.
   The deployment itself needs no GitHub access.
3. Write `terraform.tfvars.json` with the platform Terraform values that the
   command does not own:

   ```json
   {
     "gke_subnet_cidr": "10.40.0.0/20",
     "gke_pods_cidr": "10.44.0.0/16",
     "gke_services_cidr": "10.45.0.0/20",
     "gke_master_ipv4_cidr": "172.16.0.0/28",
     "gke_master_authorized_cidrs": [],
     "range_network_cidr": "10.50.0.0/16",
     "identity_allowed_email_domain": "<your-domain>"
   }
   ```

   The sizing values have defaults in
   `platform/terraform/gcp/environments/platform/variables.tf`. Set one only to
   change its default. You can also put HCL values in
   `terraform.tfvars`. When both files exist, the JSON file loads later and its
   values win.
4. Do not set the values that the command owns. The command sets `project_id`,
   `region`, `artifact_registry_location`, `environment`, `public_hostname`,
   `enable_managed_tls`, `openvpn_pool_enabled`,
   `range_host_identity_pool_size`, `range_network_zones`, and
   `ctf_content_bucket_name` from `bigrae.yaml`. Its values win over a value in
   your files.
5. Add the optional objects only if you need them: `foundation-inputs.json`,
   `model-broker-overlay.template.json`, and `retired-cluster-artifacts.json`.
   The model broker is parked (ADR-068).
6. Publish the bundle. The command validates it first:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-config publish --store gs://<bucket> --inputs /path/to/bundle
   ```

7. Show the stored bundle. The summary has no secret values:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-config show --store gs://<bucket>
   ```

8. The deploy imports the guest images that the release names when the bundle
   has no `range-images.json` roles. To import images before deployment or replace recorded images, select the required release. Run its deployer image, or pass `--release-manifest <file>`:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-images --project-id <project> \
     --store gs://<bucket> --region <region>
   ```

   The command verifies every guest against `settings.release_trust` before it
   changes anything. It imports the `kali` and `ubuntu` artifacts, and the `dc`
   artifact when the release names one, as native GCE images. It writes the
   `linux`, `kali`, and `dc` roles to `range-images.json`. A guest that did not
   change since the last import is reused. Add `--release-source <mirror prefix>`
   to read from a mirror, and `--dry-run` to check without a change. A GCE deploy
   requires the `linux` role, unless you pass `--allow-missing-range-images`.
9. To record one image by hand, use `set-range-image`. The roles are `linux`,
   `kali`, `windows`, and `dc`:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-config set-range-image --store gs://<bucket> \
     --role windows --image projects/<project>/global/images/<image>
   ```

10. To edit the bundle later, pull it into a private directory, edit it, and
    publish it again:

    ```bash
    ./scripts/bootstrap/deploy.py gcp-config pull --store gs://<bucket> --output /path/to/bundle
    ```

## Run the preflight

Check the tools and the bundle before you deploy. The check makes no change:

```bash
./scripts/bootstrap/deploy.py preflight --cloud gcp --env <environment> --store gs://<bucket>
```

The preflight checks the tools on `PATH`, loads the bundle, and renders the
Terraform values. It reports an insecure control-plane input, for example a
world-open authorized network. From a checkout, the tool check includes `git`.
The deployer image embeds its source revision, so the check omits `git` there.
The CLI delegates these tool checks to the shared preflight gate.

## First install

`gcp-install` runs the first install ([Install](#install)). To run it
separately on a published bundle:

```bash
./scripts/bootstrap/deploy.py gcp-deploy --store gs://<bucket> --first-install
```

In `--first-install` mode, the command accepts a certificate that covers the
hostname but is not Active yet. It prints a DNS instruction.

On an empty database, the deploy writes the identity facts itself. The cutover
facts have no organizations, workspaces, or users to map. The bootstrap facts
name the Identity Platform account that the infrastructure stage creates for
`settings.operator_bootstrap.admin_email`. That account becomes the first
administrator, with the separate personal-credential eligibility. Other
administrators gain no implicit eligibility.

A database with users needs the reviewed legacy conversion facts. Pass them
with `--identity-cutover-facts` and `--identity-bootstrap-facts`. See
[native identity operations](../../ops/gcp-native-identity.md).

After activation, the deploy registers the release's in-box catalog as the bootstrap administrator. Its credential permits only installation content actions. It lasts 15 minutes and is revoked after registration. When the configured operator is not the bootstrap administrator,
or the registration fails, the deploy completes with a warning. Then sign in,
issue a content credential, and run the deploy again with
`--catalog-credential-file <private 0600 file>`.

## Update and roll back

1. Get and verify the deployer image of the new release
   ([Get and verify the deployer image](#get-and-verify-the-deployer-image)).
2. Change the bundle if the release needs new inputs, and publish it again.
3. Run the deploy:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-deploy --store gs://<bucket>
   ```

   The deploy publishes the release's authorization model, re-binds the
   application to it, and registers new in-box packs.

To roll back application code, select an earlier verified release only when its schema remains compatible.
Do not retag an image.
Atomic Helm rollback does not reverse database, identity, policy, or Terraform changes.
Use [RB015](../../runbooks/rb015-database-migrations.md) before rollback that needs data recovery.

## What the deploy does

The command runs these stages in order:

| Stage | Identity | Steps |
| --- | --- | --- |
| Inputs | Your identity, then deploy | Load and validate the bundle. Check the tooling revision and release-image provenance. Import release base images when the bundle has none. Take the lock. |
| Infrastructure | Deploy | Initialize Identity Platform and harden the state bucket. Remove bindings to deleted custom roles. Apply Terraform and rewrite live bucket objects with their keys. Verify range audit telemetry. Seed the provider account without an application grant. |
| Preconditions | Deploy | Check the GCE range inputs and images. |
| Images | Deploy | Copy each release image and its attestations into the deployment registry by digest. |
| Scan | Release scan | Scan each exact digest with Trivy for HIGH and CRITICAL findings. |
| Verify | Deploy | Verify the provenance of each image. There is no bypass. |
| Rollout | Deploy | Create initial OpenFGA credentials and reconcile SQL duties. Probe and drain when required. Migrate storage and publish the release model. Verify native activation. Restore Helm and wait for readiness. Roll out OpenVPN, record running images, and wait for ingress and certificate. |
| Catalog | Bootstrap administrator, or a supplied native credential | Register the in-box catalog after readiness through ordinary registration, conformance and publication. A failure leaves catalog work pending with a warning; the application stays active. |
| Smoke | Deploy | Run the advisory range smoke. |

`--stage infrastructure` and `--stage rollout` run one stage. Each still
checks the tooling revision and verifies the release images before any change.
`--stage rollout` also imports and scans the release images.

Each stage sets only its purpose identity for every child process. The command
uses a private `KUBECONFIG`, so it does not change your kubeconfig contexts.
The Helm upgrade is atomic: a failed upgrade rolls back the Helm release. A
failed Terraform apply does not roll back.

## Smoke and exit status

| Exit status | Meaning |
| --- | --- |
| 0 | The deployment is current. |
| 1 | A stage failed. The command printed the reason. |
| 2 | The command arguments are not valid. |
| 3 | The deployment is current, but the advisory smoke failed. |

Add `--no-smoke` to skip the smoke. Run the smoke alone with:

```bash
./scripts/bootstrap/deploy.py gcp-smoke --store gs://<bucket>
```

The smoke creates billable range resources and requests their teardown.
An empty smoke email also skips the check.
A skipped smoke does not qualify the deployment.
Confirm terminal range state, absent provider resources, and removal of the temporary smoke Job and identity Secret.

## Evidence

The commands write evidence to `<project>-release-evidence`. Use
`--evidence-bucket` for a different bucket.

| Prefix | Writer | Objects |
| --- | --- | --- |
| `release-scans/<revision>/<run id>/<attempt>/` | Release-scan identity | `release-manifest.json`, one `<image>-trivy.json` for each image, and `verdict.json` |
| `deployments/<revision>/<run id>/<attempt>/` | Deploy identity | `running-image-ids.json` and `verdict.json` |

`verdict.json` holds the result, an opaque locator, and the SHA-256 of the raw
evidence files in its prefix. The digest does not include `verdict.json`. The
command makes a run id from the time and a random suffix. Set `--run-id` and
`--attempt` to use your own values.

## Deployment lock

The command creates `locks/deploy.lock` in the config bucket before it changes
anything. It removes the lock at the end, also when a stage fails. A second
command fails while the lock exists and names the holder.

1. Make sure that no other deploy or destroy runs for the deployment.
2. Remove a stale lock with `--break-lock` on the next command. The command
   removes the lock with no prompt:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-deploy --store gs://<bucket> --break-lock
   ```

## Tear down

1. Get the deployer image of the release that the deployment runs.
2. Run the destroy. `--confirm` must equal the deployment name:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-destroy --store gs://<bucket> --confirm <environment>
   ```

The destroy runs as the destroy identity. It first verifies that the tooling
revision equals the release revision and that the release images verify. It then takes the lock and lifts Cloud SQL deletion protection. It removes permanent KMS key rings and keys from state. It runs `terraform destroy` with bounded retries.

These items stay after a teardown:

- the foundation: the purpose identities, the state bucket, the
  release-evidence bucket, the config bucket, and their key ring;
- the Artifact Registry key ring and key, and the platform bucket key ring and
  keys. The next deploy adopts them. A destroy that you run again after an
  interruption also adopts them;
- the resources that Terraform does not own, for example the operator password
  secret and the imported range guest images.

Generated OpenFGA secrets are also retained outside the platform Terraform state.
Retained resources can continue to incur costs.
Teardown does not remove the Google Cloud project or bypass retention locks.
For failure, use [RB023](../../runbooks/rb023-gcp-deployment.md), then rerun the same release command after correcting the cause.

## Bucket encryption keys

Each Terraform-owned bucket uses a customer-managed Cloud KMS key. The
[GCS CMEK design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/gcp-gcs-cmek-design-2564.md) gives the
architecture.

| Key ring | Location | Keys | Owner |
| --- | --- | --- | --- |
| `<name_prefix>-foundation-gcs` | Foundation region | `release-evidence`, `deployment-config` | `gcp-foundation` |
| `<name_prefix>-image-export-gcs` | Foundation region | `staging`, `daisy-scratch` | `gcp-foundation`, build projects only |
| `shifter-<environment>-gcs` | Deployment region | `assets`, `audit-logs` | `gcp-deploy` |
| Pack bucket name, dots changed to hyphens | Pack bucket location | `raes-packages` | Your Terraform root |

Each key rotates every 90 days. Rotation makes a new primary version for new
writes. It does not re-encrypt old objects, and old versions stay enabled.

### Upgrade a deployment to bucket keys

1. Apply the foundation again with the release tooling:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-foundation --inputs /path/to/foundation.json --yes
   ```

2. Run the deploy:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-deploy --store gs://<bucket>
   ```

3. If you use the private pack bucket, apply your pack bucket root. Then
   rewrite its objects with the `package_bucket_kms_key` output:

   ```bash
   ./scripts/bootstrap/deploy.py gcp-cmek-migrate --bucket <pack-bucket> --key <key>
   ```

Do not use `--reconcile-foundation-image-network` before step 1. That plan
accepts only image-network changes, so it stops on the new keys.

Each command rewrites the live objects that do not use the bucket key. Each
rewrite pins the object generation, so a concurrent upload is not replaced. A
second run rewrites nothing.

### Objects that keep the Google-managed key

The command reports these objects and does not change them:

- noncurrent versions. The `assets` and deployment config buckets keep them
  until you delete them;
- soft-deleted objects, until the soft-delete period ends;
- live objects in the release-evidence bucket, until the lifecycle rule deletes
  them after 365 days;
- live objects with `*`, `?`, `[`, or `]` in the name.

To list the noncurrent versions that do not use a key, run this command:

```bash
gcloud storage objects list "gs://<bucket>/**" \
  --format="table(name,generation,kms_key,noncurrent_time)" \
  --filter='noncurrent_time:* AND NOT kms_key:"<key>"'
```

### Repair key access

If reads or writes fail with `Permission denied on Cloud KMS key`, do these
steps:

1. Run the owner command again (`gcp-foundation`, `gcp-deploy`, or your pack
   bucket root). Terraform restores the Storage service agent grant.
2. If a key version is disabled, enable it with an account that has
   `roles/cloudkms.admin`. The lifecycle identities can not do this:

   ```bash
   gcloud kms keys versions enable <version> --key <key> --keyring <key-ring> \
     --location <location> --project <project>
   ```

Do not remove a bucket default key to restore access. A destroyed key version
can not be recovered after its scheduled destruction date.

## Identity options

| Option | Use |
| --- | --- |
| `--name-prefix` | The purpose identity prefix when it is not `shifter-<environment>`. |
| `--deploy-service-account`, `--release-scan-service-account`, `--destroy-service-account` | An explicit purpose identity. With an explicit deploy identity, the command also reads the bundle as that identity. |
| `--environment` | The deployment name when it is not `deployment.name`. |

A derived identity is `<name prefix without hyphens>-deploy`, `-scan`, or
`-destroy` at `<project>.iam.gserviceaccount.com`. A service account ID has 30
characters or fewer, so a derived name can be too long. The command then stops
and tells you to pass the identity explicitly.
