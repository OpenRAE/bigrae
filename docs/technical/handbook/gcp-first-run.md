# Install BigRAE on GCP

This page installs BigRAE in a GCP project from a published release. You do
these steps in order. Each step links to the
[GitHub-less GCP deployment guide](gcp-github-less-deployment.md), which has the
full detail. The install needs no GitHub account, no fork, and no repository
checkout.

AWS support comes in an upcoming release.

## What you need

- A GCP project with billing on.
- A Google identity that can administer the IAM of the project: `roles/owner`,
  or `roles/resourcemanager.projectIamAdmin`, `roles/iam.roleAdmin`, and
  `roles/iam.serviceAccountAdmin`.
- A domain that you control, and access to its DNS records.
- An email address in that domain for the first administrator.
- Docker, the `gcloud` CLI, [ORAS](https://oras.land/), and
  [cosign](https://docs.sigstore.dev/cosign/) on your workstation.
- If your configuration uses Vertex AI models, enable each model in the
  project. The Vertex AI API alone does not enable a model.

The install creates billable resources. Run it only in a project that you are
authorized to use.

## 1. Sign in to Google Cloud

```bash
gcloud auth login
gcloud auth application-default login
```

The commands use your credentials only to impersonate the deployment
identities that the install creates.

## 2. Select a release

A release is a [GitHub release](https://github.com/OpenRAE/bigrae/releases)
`vX.Y.Z`. Its deployer image is `ghcr.io/openrae/bigrae/deployer-gcp`, tagged
with the full commit SHA of the release. The registry is public. Releases
v4.1.1 and earlier have no deployer image.

Set the registry and the release commit:

```bash
REG=ghcr.io/openrae/bigrae
REV=$(git ls-remote https://github.com/OpenRAE/bigrae refs/tags/vX.Y.Z | cut -f1)
```

## 3. Get and verify the deployer image

```bash
DIGEST=$(oras resolve "$REG/deployer-gcp:$REV")
cosign verify-attestation --type https://slsa.dev/provenance/v1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "https://github.com/OpenRAE/bigrae/.github/workflows/release-gcp.yml@refs/heads/main" \
  --certificate-github-workflow-sha "$REV" "$REG/deployer-gcp@$DIGEST"
```

Use the digest, not the tag, in every later command. See
[Get and verify the deployer image](gcp-github-less-deployment.md#get-and-verify-the-deployer-image).

## 4. Write the deployment input bundle

Create a private directory, for example `~/bigrae-bundle`. Write two files in
it:

- `bigrae.yaml`: the deployment name, the hostname, the project, the region,
  the range zone, and the first administrator.
- `terraform.tfvars.json`: the network ranges and the allowed email domain.

Copy both examples from
[Author and publish the deployment input bundle](gcp-github-less-deployment.md#author-and-publish-the-deployment-input-bundle),
steps 2 to 4. For a release from `OpenRAE/bigrae`, set `settings.release_trust`
to these values:

```yaml
release_trust:
  github_repository_id: "1241599684"
  github_owner_id: "308592074"
```

Keep the bundle out of source control. It holds the identity of your
deployment.

## 5. Run the install

```bash
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e CLOUDSDK_CONFIG=/gcloud \
  -e GOOGLE_APPLICATION_CREDENTIALS=/gcloud/application_default_credentials.json \
  -v "$HOME/.config/gcloud:/gcloud" \
  -v "$HOME/bigrae-bundle:/bundle:ro" \
  "$REG/deployer-gcp@$DIGEST" gcp-install --inputs /bundle
```

The install applies the foundation, creates the first operator password,
publishes the bundle to `gs://<project>-deployment-config`, and runs the first
deploy. A first install takes about 40 minutes. When a step fails, fix the
cause and run the same command again. See [Install](gcp-github-less-deployment.md#install).

The output shows two values. Record them:

- the ingress address;
- the command that reads the first operator password.

## 6. Point DNS at the deployment

Create a DNS A record for `deployment.domain` at the ingress address. Do not
proxy the record.

## 7. Complete the install

```bash
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e CLOUDSDK_CONFIG=/gcloud \
  -e GOOGLE_APPLICATION_CREDENTIALS=/gcloud/application_default_credentials.json \
  -v "$HOME/.config/gcloud:/gcloud" \
  "$REG/deployer-gcp@$DIGEST" gcp-deploy --store gs://<project>-deployment-config
```

The deploy waits up to 60 minutes for the managed certificate to become
Active. It then runs the post-deploy smoke, which creates and destroys one
range. Exit status 0 means the deployment is current. Exit status 3 means the
deployment is current but the smoke failed. See
[Smoke and exit status](gcp-github-less-deployment.md#smoke-and-exit-status).

## 8. Sign in

Open `https://<deployment.domain>`. Sign in with the first administrator email
and the password from step 5. The in-box catalog holds the `smoke-linux`
scenario: a Kali attacker and an Ubuntu victim.

Next, [launch your first range](../../getting-started/quickstart.md).

## When something fails

- [RB023](../../runbooks/rb023-gcp-deployment.md) lists the failure symptoms
  and the fix for each deploy stage.
- [GCP tenant standup gotchas](../../dev/gcp-tenant-standup-gotchas.md) lists
  known problems and their fixes.

## Update and remove

- To update, verify the deployer image of the newer release, then run
  `gcp-deploy` from it. See
  [Update and roll back](gcp-github-less-deployment.md#update-and-roll-back).
- To remove the deployment, see
  [Tear down](gcp-github-less-deployment.md#tear-down).
