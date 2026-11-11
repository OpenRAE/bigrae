# Contributor GCP releases and test deploys

Part of the BigRAE deploy and operations docs; start at the [documentation home](../index.md).

Use these procedures to publish a GCP release, and to test deploy tooling before a release.
An operator installs from a published release with [Install on Google Cloud](../getting-started/install-gcp.md).
The [GCP deployment handbook](../technical/handbook/gcp-github-less-deployment.md) is the command reference.
Failure handling is in [RB023](../runbooks/rb023-gcp-deployment.md).

A build from `dev` or `deploy-test` is a contributor test artifact.
It is not a production release, and it does not qualify a live deployment.
See [deployment compatibility](../technical/platform_infrastructure/deployment-compatibility.md).

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
   The run log also prints `Attestation created for <registry>/deployer-gcp@sha256:<digest>`.
4. After the first release only, make each package public
   ([Make new release packages public](#make-new-release-packages-public)).

The workflow publishes to `ghcr.io/<owner>/<repository>`, in lower case, with
the workflow `GITHUB_TOKEN`. It uses no cloud identity.
It tags each image with the source revision only.

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

After the build, read the release manifest from the deployer image.
Check that `source_revision` equals the commit that you released.
Check that `base_images` and `authorization_model` are present.

## Release from dev or a deploy-test branch

`release-gcp.yml` publishes from `refs/heads/main`, `refs/heads/dev`, and
`refs/heads/deploy-test`. A Release Please release on `main` starts it
automatically. GitHub dispatches a workflow only after the file is on the
default branch. After `release-gcp.yml` is on `main` once, dispatch it on
another release ref:

```bash
gh workflow run release-gcp.yml --ref deploy-test
```

The run uses the workflow file of that ref. Each release ref needs a deployment
branch policy in the `gcp-release` Environment. Protect `deploy-test` against
force pushes and deletion. The release goes to the public registry
`ghcr.io/<owner>/<repository>`, so every deployment can use it.

`gcp-deploy` requires that its own revision equals the release revision. A deploy
fix therefore needs a new release. Put the fixes on `deploy-test` and release
from it, so that a test cycle does not wait for a merge to `dev`.
Keep `deploy-test` equal to `origin/dev` plus the open fix pull requests.
When they drift, merge `origin/dev` into it and apply the open pull requests again.

The GitHub API rate limit is shared by every session of the account.
Poll a release run every few minutes, not every few seconds.

## Release build failures

| Step | Cause and fix |
| --- | --- |
| Select the guest images | A `gce-<role>` package is missing under `ghcr.io/<owner>/<repository>`, or its newest publication does not verify ([Guest images must exist in the release registry](#guest-images-must-exist-in-the-release-registry)). Build and publish the guest again with `packer-gcp.yml`. |
| Deployer provider mirror | A Terraform root or module lock file does not record a provider. Run `terraform init -backend=false` for that directory and commit the lock change. |
| Scan the deployer image | A tool binary has a fixable HIGH or CRITICAL finding. Bump the tool, or build it from a pinned source commit when no fixed vendor build exists. |
| A build stage that fetches source | Check the pinned commit. An annotated tag object SHA is not the commit SHA. |
| Render the authorization model | The platform environment did not sync, or the OpenFGA CLI image did not run. |
| Control-plane image scan at deploy time | A bundled dependency is vulnerable. Fix it in the image build; see the Guacamole bundled-jar patch for the pattern. |

A failed scan is a finding to fix, not a gate to relax.
Fix the image or the tool, open a pull request to `dev`, and release again.
When a Release Please call fails, or a `release-superseded` job names a commit, run the Release Please run of that commit again.

## Guest images must exist in the release registry

`release-gcp.yml` takes the newest guest image of each role from
`ghcr.io/<owner>/<repository>/gce-<role>`. The release stops when a role is
missing or its provenance does not verify against this repository. After a
repository transfer, publish the guests again with `packer-gcp.yml` from the
new repository, and make the packages public.
The release does not build guest images (#2668).
To change a guest, run `packer-gcp.yml` in the developer build project, then release again.

## Make new release packages public

GHCR makes a new package private. After the first release from a repository,
make the `portal`, `provisioner`, `guacd`, `guacamole-client`, `openvpn`, and
`deployer-gcp` packages public in the GitHub package settings. Until then, a
deploy cannot pull the release images.
Do the same for each `gce-<role>` guest package after its first publication.

## Read the release manifest without Docker

A checkout deploy needs `--release-manifest`. The deployer image holds the
manifest at `/opt/bigrae/release.json`, and the release run summary prints it.
Without Docker, extract it from the image layer with ORAS:

```bash
REF=<release registry>/deployer-gcp@<digest>
IMAGE=$(oras manifest fetch "$REF" | jq -r '.manifests[0].digest')
for layer in $(oras manifest fetch "${REF%@*}@$IMAGE" | jq -r '.layers[] | select(.size < 200000) | .digest'); do
  oras blob fetch "${REF%@*}@$layer" --output - | tar -xzO opt/bigrae/release.json 2>/dev/null > release.json && break
done
```

The release registry is public, so ORAS needs no credentials for it. For an
Artifact Registry mirror, ORAS uses the Docker credential helper, so
`docker-credential-gcloud` must be on `PATH`.

## Deploy from a checkout

The deployer image holds every deploy tool at the release version. Without it,
run the commands from a worktree of the release revision.
`gcp-deploy` stops when `HEAD` is not the release revision or when tracked
files have changes. Use a separate worktree for each release, so that other
work does not change it:

```bash
git worktree add --detach <path> <release revision>
cd <path>
uv run --project scripts/bootstrap scripts/bootstrap/deploy.py gcp-deploy \
  --store gs://<bucket> --release-manifest release.json
```

Run each command through the `scripts/bootstrap` uv project. The project holds
the Python dependencies of the commands. The handbook writes
`./scripts/bootstrap/deploy.py`; from a checkout, that means
`uv run --project scripts/bootstrap scripts/bootstrap/deploy.py <command>`.

Install the tool versions that `platform/deployer/gcp/Dockerfile` pins.
Put these tools on `PATH`: `gcloud`, `gke-gcloud-auth-plugin`, `terraform`,
`kubectl`, `helm`, `oras`, `trivy`, `git`, and `uv`.
The command stops before any change when one is missing.

Use Helm 3. The deployer image and retained CI adapter pin `v3.22.1`. Helm 4 is a separate major release without chart qualification here.

`kubectl`, `helm`, and `oras` install as static binaries into a `PATH` directory
without root.

### Install `gke-gcloud-auth-plugin` without root

The deploy command requires `gke-gcloud-auth-plugin` on `PATH`; the deployer
image already holds it. On a Debian/apt `gcloud`, the component manager is
disabled, so `gcloud components install` fails. Install the plugin without root
by extracting the apt package:

```bash
cd "$(mktemp -d)"
apt-get download google-cloud-cli-gke-gcloud-auth-plugin
dpkg-deb -x google-cloud-cli-gke-gcloud-auth-plugin_*.deb ./x
cp ./x/usr/lib/google-cloud-sdk/bin/gke-gcloud-auth-plugin ~/.local/bin/
```

## Test deploy tooling without a release

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

## Hand-patch a checkout deploy during a test cycle

`gcp-deploy` reads `BIGRAE_SOURCE_REVISION` before it reads `git`. The deployer
image sets it. To test a fix before the next release, cherry-pick the fix into
a worktree of the release revision and set the variable to that revision:

```bash
BIGRAE_SOURCE_REVISION=<release revision> \
  uv run --project scripts/bootstrap scripts/bootstrap/deploy.py gcp-deploy \
  --store gs://<bucket> --release-manifest release.json
```

The release images and their provenance stay those of the release. Use this
only for a fix that is already in a pull request, and release again after it
merges to `deploy-test`.

## Manual Terraform runs

The execution root is `platform/terraform/gcp/environments/platform`.
`gcp-deploy` passes the bundle's values and its generated var files, and it
isolates `TF_DATA_DIR` automatically.
Manual commands must select the values and `TF_DATA_DIR` explicitly.
Follow [deployment configuration](deployment-configuration.md) before reusing retained state.

`gcp-foundation` sets the quota project of its child processes. A manual
Terraform run uses the quota project in your ADC file. If that project is deleted, each call fails with the error `The requested
project was not found`. Set the quota project and a private data directory for the run:

```bash
export GOOGLE_CLOUD_QUOTA_PROJECT=<project> TF_DATA_DIR="$(mktemp -d)"
```

## Never commit a deployment identity

Do not put a real project ID or service-account email into the chart values
(`platform/charts/shifter/values*.yaml`) or into any other committed file. The
real deploy identity is reconnaissance-sensitive and tenant-specific (ADR-004-R14,
ADR-011). The deploy command renders the image repositories and workload
identities from the Terraform outputs into private generated values at deploy
time. The `no-live-gcp-deploy-identity` adr-guard check scans the chart values.
