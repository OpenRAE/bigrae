# Install on Google Cloud

This procedure installs BigRAE from a published container. The container holds
the installer, Terraform, Helm, and the other deployment tools.
You do not need a repository clone, Python, Node.js, or a source build.

Use [Deploy with a coding agent](deploy-with-agent.md) to delegate these steps.
AWS support is coming. This procedure is for Google Cloud only.

## Before you start

### Prepare the machine

Use a persistent Linux machine with a Bash terminal. The release container uses
the Linux `amd64` architecture. On Windows, use Ubuntu in WSL2 with Docker
Desktop integration enabled.

Install these tools on that machine:

| Tool | Installation instructions | Check |
| --- | --- | --- |
| Docker | [Docker installation](https://docs.docker.com/engine/install/) | `docker info` must connect to the Docker service. |
| Google Cloud CLI | [Google Cloud CLI installation](https://docs.cloud.google.com/sdk/docs/install-sdk) | `gcloud version` must print a version. |
| Git | [Git installation](https://git-scm.com/downloads) | `git --version` must print a version. |
| ORAS | [ORAS installation](https://oras.land/docs/installation) | `oras version` must print a version. |
| cosign | [cosign installation](https://docs.sigstore.dev/cosign/system_config/installation/) | `cosign version` must print a version. |

The machine needs space for the release container and guest image downloads.
Guest images can be several gigabytes each. It must reach Google Cloud,
GitHub, `ghcr.io`, and Sigstore over HTTPS.

Run every command below in the same Bash session. Run one block at a time.
If a command fails, stop at that step and read its error.

### Prepare cloud access

You need:

- A Google Cloud project for this installation, with billing enabled.
- Project administration access for the initial installation.
- A hostname and access to its DNS provider.
- A Google account email address for the first administrator.
- An authenticator application for the administrator's second sign-in factor.

Identity and Access Management (IAM) controls Google Cloud permissions.
Project Owner (`roles/owner`) has the project access needed for initial setup.
Editor alone does not have the required IAM administration access.
If your organisation uses delegated roles, its administrator must grant the
required project, IAM, service-account, storage, encryption, network, and compute permissions.
See [project roles](../technical/handbook/gcp-github-less-deployment.md#prerequisites-and-roles).

If your configuration uses Vertex AI models, enable each model in the project.
The Vertex AI API alone does not enable a model.

The project must permit the required Google services and service-account creation.
Project permissions do not override an organisation policy.
Ask your cloud administrator to resolve a policy denial.

The installation creates billable resources. These include a Kubernetes cluster,
databases, networking, storage, and guest images. Allow at least 40 minutes for a
first installation. Image transfers and certificate validation can take longer.
The foundation creates a release-evidence bucket with locked 90-day retention.
Its retained objects cannot be deleted before that period ends.

The installer creates its deployment service accounts, storage, encryption keys,
initial password, application secrets, and guest image copies.
You do not need a GitHub account, GitHub repository administration, Actions
environments, or runners.
The installed application does not need your GitHub credentials.

## 1. Record the installation inputs

Replace the example values. Use the project ID from the Google Cloud console.
Use a short deployment name, such as `training`. Use nine characters or fewer.

```bash
set -o pipefail
PROJECT_ID='your-project-id'
DEPLOYMENT_NAME='training'
PORTAL_HOSTNAME='ranges.example.com'
OPERATOR_EMAIL='operator@example.com'
REGION='us-central1'
ZONE='us-central1-a'
```

The hostname must belong to a domain that you control.
The zone must be in the selected region.
The operator email will also be the first portal administrator's email.
`pipefail` makes a failed install remain a failure when you also save its log.

Create a private directory for this installation:

```bash
umask 077
mkdir -p "$PWD/bigrae-install-$DEPLOYMENT_NAME"
DEPLOY_DIR="$PWD/bigrae-install-$DEPLOYMENT_NAME"
```

Keep this directory. Do not add its files to a source repository.

## 2. Sign in

```bash
gcloud auth login "$OPERATOR_EMAIL" --no-activate
gcloud auth application-default login "$OPERATOR_EMAIL"
```

Complete each browser sign-in. Select the same Google account for both Google
commands. The second Google command stores Application Default Credentials
for the deployment tools. It replaces any existing default application credentials
on this machine.

Check the selected project and billing:

```bash
CLOUDSDK_CORE_ACCOUNT="$OPERATOR_EMAIL" \
  gcloud projects describe "$PROJECT_ID" --format='table(projectId,projectNumber)'
CLOUDSDK_CORE_ACCOUNT="$OPERATOR_EMAIL" \
  gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
```

The first command must show the correct project. The second must print `True`.
Resolve an access error or disabled billing before you continue.

## 3. Select and verify a release

1. Open the [releases](https://github.com/OpenRAE/bigrae/releases).
2. Select the release approved for your installation. Releases v4.1.1 and
   earlier have no deployer image.

Set the release tag and get its source revision:

```bash
RELEASE_TAG='vX.Y.Z'
REG=ghcr.io/openrae/bigrae
RELEASE_REVISION="$(git ls-remote https://github.com/OpenRAE/bigrae \
  "refs/tags/$RELEASE_TAG" "refs/tags/$RELEASE_TAG^{}" | tail -n 1 | cut -f 1)"
printf '%s\n' "$RELEASE_REVISION"
```

The command must print one 40-character revision. If it prints nothing, check
the release tag. This command reads the tag. It does not clone the repository.

Resolve the deployer image digest and verify its build provenance:

```bash
DIGEST="$(oras resolve "$REG/deployer-gcp:$RELEASE_REVISION")"
DEPLOYER_IMAGE="$REG/deployer-gcp@$DIGEST"
cosign verify-attestation --type https://slsa.dev/provenance/v1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "https://github.com/OpenRAE/bigrae/.github/workflows/release-gcp.yml@refs/heads/main" \
  --certificate-github-workflow-sha "$RELEASE_REVISION" \
  "$DEPLOYER_IMAGE" > /dev/null
```

Continue only if verification succeeds. A failed verification blocks installation.
The check accepts only a release build from `main` at the selected revision.
`DEPLOYER_IMAGE` ends with `@sha256:` and a digest. This address identifies the
exact container. Do not replace it with a moving image tag.
See [Get and verify the deployer image](../technical/handbook/gcp-github-less-deployment.md#get-and-verify-the-deployer-image).

Download the verified container and retain its release manifest:

```bash
docker pull "$DEPLOYER_IMAGE"
docker run --rm --entrypoint cat "$DEPLOYER_IMAGE" /opt/bigrae/release.json \
  > "$DEPLOY_DIR/release.json"
printf '%s\n' "$DEPLOYER_IMAGE" > "$DEPLOY_DIR/deployer-image.txt"
printf '%s\n' "$RELEASE_REVISION" > "$DEPLOY_DIR/release-revision.txt"
```

The installer uses this manifest to verify the application images.
Selecting a published release does not start a new release build.

## 4. Create the two input files

Create `bigrae.yaml`:

```bash
cat > "$DEPLOY_DIR/bigrae.yaml" <<EOF
version: 1
backend: gcp
deployment:
  name: $DEPLOYMENT_NAME
  domain: $PORTAL_HOSTNAME
  profile: prod
secrets:
  django_secret_key: prompt
settings:
  project_id: $PROJECT_ID
  region: $REGION
  dynamic_secret_project_id: $PROJECT_ID
  range_cells:
    backend: gce
    zone: $ZONE
  participant_openvpn:
    enabled: false
  operator_bootstrap:
    admin_email: $OPERATOR_EMAIL
  post_deploy_smoke:
    user_email: $OPERATOR_EMAIL
  release_trust:
    github_repository_id: "1241599684"
    github_owner_id: "308592074"
EOF
```

The installer creates the Django secret. Keep the literal value `prompt` in this
configuration. Do not replace it with a password.
The example uses one project for the application, guest virtual machines, and runtime secrets.
Custom scenario packs can require additional projects or inputs.

Create `terraform.tfvars.json`:

```bash
OPERATOR_DOMAIN="$(printf '%s' "$OPERATOR_EMAIL" | cut -d @ -f 2)"
cat > "$DEPLOY_DIR/terraform.tfvars.json" <<EOF
{
  "gke_subnet_cidr": "10.40.0.0/20",
  "gke_pods_cidr": "10.44.0.0/16",
  "gke_services_cidr": "10.45.0.0/20",
  "gke_master_ipv4_cidr": "172.16.0.0/28",
  "gke_master_authorized_cidrs": [],
  "range_network_cidr": "10.50.0.0/16",
  "identity_allowed_email_domain": "$OPERATOR_DOMAIN"
}
EOF
```

These network ranges are for a new, separate installation.
If you connect it to an existing network, have its administrator select
ranges that do not overlap before you install.
The email domain limits which email domain the identity configuration accepts.
It does not grant application permissions to every person in that domain.

## 5. Define the container command

Copy this complete block into the same terminal:

```bash
GCLOUD_CONFIG_DIR="$(gcloud info --format='value(config.paths.global_config_dir)')"
deploy() {
  docker run --rm -i \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e CLOUDSDK_CONFIG=/gcloud \
    -e CLOUDSDK_CORE_ACCOUNT="$OPERATOR_EMAIL" \
    -e GOOGLE_APPLICATION_CREDENTIALS=/gcloud/application_default_credentials.json \
    --mount "type=bind,src=$GCLOUD_CONFIG_DIR,dst=/gcloud" \
    --mount "type=bind,src=$DEPLOY_DIR,dst=/inputs,readonly" \
    "$DEPLOYER_IMAGE" "$@"
}
```

`deploy` is a shell function. It runs the selected installer container with your
Google credentials and the two input files. It selects the operator account
for that container. It does not change your default Google account.
If you open another terminal, set the variables and define this function again.

## 6. Start the installation

```bash
deploy gcp-install --inputs /inputs --operator "$OPERATOR_EMAIL" \
  2>&1 | tee "$DEPLOY_DIR/install.log"
```

The command performs these steps:

1. Validate the input files.
2. Create deployment identities, encrypted storage, and the configuration bucket.
3. Create the initial administrator password in Secret Manager.
4. Import the release's signed guest images.
5. Create the platform infrastructure and import its application images.
6. Scan the exact application images.
7. Start the application, configure identity and permissions, and register the initial catalog.

The output shows the ingress address and the command that reads the initial
password. Record both.

Keep the terminal open. To watch the log from another terminal, use
`tail -f` with the full path to `install.log`.
The first install can complete while its certificate is still inactive.
Continue with the DNS and completion steps below.
For a failure, use [Recover a failed command](#recover-a-failed-command).

## 7. Create the DNS record

Get the installation's public IP address:

```bash
CLOUDSDK_CORE_ACCOUNT="$OPERATOR_EMAIL" \
  gcloud compute addresses describe "shifter-$DEPLOYMENT_NAME-platform-ip" \
  --global --project "$PROJECT_ID" --format='value(address)'
```

If the address does not exist yet, wait for infrastructure creation to reach
that step. You can check from a second terminal while installation continues.

In your DNS provider, create this record:

| Field | Value |
| --- | --- |
| Type | `A` |
| Name | The hostname from step 1. For `ranges.example.com`, some providers show this as `ranges`. |
| Address | The public IP address printed by the command. |
| Proxy | Off. Use DNS-only mode. |

DNS must resolve the hostname to this IP before Google can issue its certificate.
Do not change an existing record for a different installation.

## 8. Complete the installation checks

After DNS resolves, run:

```bash
deploy gcp-deploy --store "gs://$PROJECT_ID-deployment-config" \
  2>&1 | tee "$DEPLOY_DIR/complete.log"
```

This command uses the stored configuration. It waits for the certificate and
checks the running application images. It also runs the configured range smoke
check, which creates and destroys a test range.

Confirm all of these results before you report a completed installation:

- `Running workload images match the approved release`.
- The managed certificate is active.
- `Post-deploy smoke passed`, with no message that the smoke was skipped.
- `https://` followed by your hostname opens the sign-in page without a certificate error.

A healthy application does not prove that every custom scenario works.
Test each scenario before you give it to participants.

## 9. Sign in

Retrieve the initial password in your own terminal:

```bash
CLOUDSDK_CORE_ACCOUNT="$OPERATOR_EMAIL" \
  gcloud secrets versions access latest \
  --secret "shifter-$DEPLOYMENT_NAME-operator-password" --project "$PROJECT_ID"
```

This command prints a password. Do not copy its output into a support issue,
agent conversation, or installation log.

1. Open `https://` followed by the hostname from step 1.
2. Sign in with the operator email and initial password.
3. Follow the portal's authenticator setup steps.
4. Complete the second-factor sign-in.
5. Use [Launch your first range](quickstart.md) to check a scenario and its
   teardown.

## Resume in a new terminal

Set these values from your installation record. Use the full path to the
directory that contains the saved files:

```bash
set -o pipefail
PROJECT_ID='your-project-id'
DEPLOYMENT_NAME='training'
OPERATOR_EMAIL='operator@example.com'
DEPLOY_DIR='/full/path/to/bigrae-install-training'
DEPLOYER_IMAGE="$(cat "$DEPLOY_DIR/deployer-image.txt")"
```

Define the shell function again with step 5. If authentication has expired,
repeat the Google sign-ins from step 2.

## Update an installation

Keep the same project, deployment name, configuration bucket, and input directory.
Select and verify the new release with step 3. This changes `DEPLOYER_IMAGE`
to the new immutable image. The shell function then uses that image.

```bash
deploy gcp-deploy --store "gs://$PROJECT_ID-deployment-config" \
  2>&1 | tee "$DEPLOY_DIR/update.log"
```

Do not use `gcp-install` to update an existing installation.
Check the same completion results as step 8.
Read the [scenario transition rules](../technical/handbook/scenario-contract-transition.md)
before an update that changes the scenario runtime. Some updates require ranges
to finish before the update starts.

To change the configuration, edit the two local input files and publish them:

```bash
deploy gcp-config publish --store "gs://$PROJECT_ID-deployment-config" --inputs /inputs
deploy gcp-deploy --store "gs://$PROJECT_ID-deployment-config"
```

## Recover a failed command

Keep the logs and the selected release image. Record the last `Running:` line.
Use the [deployment runbook](../runbooks/rb023-gcp-deployment.md) for that stage.

| Result | Action |
| --- | --- |
| Sign-in expired | Repeat both Google sign-ins from step 2. Retry the failed command. |
| Access denied | Ask the project administrator for the named permission. Retry after it takes effect. |
| First install failed | Fix the reported cause. Run the same `gcp-install` command. It retains completed work. |
| Certificate inactive | Check the DNS address and turn off its proxy. Run the completion command from step 8. |
| Image scan or attestation failed | Stop. Give the maintainer the failed check and release revision. |
| Another deploy holds the lock | Check whether it is still running. Wait for active work to finish. |
| Range smoke failed | The application can be deployed while the smoke is failed. Use the runbook; do not report success. |

Do not delete Terraform state, range records, or locks to hide a failed step.
Use `--break-lock` only after you confirm that its recorded owner has stopped.
The deploy command returns `0` on success, `1` on a failed stage,
`2` for invalid arguments, and `3` when deployment completed but its smoke failed.

## Remove an installation

This command removes the platform resources. Confirm the project and deployment
name before you run it:

```bash
deploy gcp-destroy --store "gs://$PROJECT_ID-deployment-config" \
  --confirm "$DEPLOYMENT_NAME"
```

The foundation, protected encryption keys, retained evidence, initial secrets,
and imported guest images remain. Some remaining resources can still incur costs.
Removal does not delete the Google Cloud project.
Use the [teardown reference](../technical/handbook/gcp-github-less-deployment.md#tear-down)
to inspect the retained resources.
