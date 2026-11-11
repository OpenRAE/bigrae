---
name: gcp-release
description: Publish and verify a GitHub-less GCP release with release-gcp.yml (ADR-070) and read its deployer digest and manifest. Use when a GCP deploy needs a new release or a release build fails.
---

# Publish a GCP release

A GCP deployment runs only a release that `.github/workflows/release-gcp.yml`
builds and signs. The procedure and the facts are in these documents:

| Need | Document |
| --- | --- |
| Publish a release, and read its digest and manifest | [Publish a release](../../../docs/dev/gcp-contributor-deploy.md#publish-a-release) |
| Release from `dev` or `deploy-test`, and keep `deploy-test` current | [Release from dev or a deploy-test branch](../../../docs/dev/gcp-contributor-deploy.md#release-from-dev-or-a-deploy-test-branch) |
| A failed release build | [Release build failures](../../../docs/dev/gcp-contributor-deploy.md#release-build-failures) |
| Guest images and package visibility | [Guest images](../../../docs/dev/gcp-contributor-deploy.md#guest-images-must-exist-in-the-release-registry) and [Make new release packages public](../../../docs/dev/gcp-contributor-deploy.md#make-new-release-packages-public) |
| The release manifest without Docker | [Read the release manifest without Docker](../../../docs/dev/gcp-contributor-deploy.md#read-the-release-manifest-without-docker) |
| Which published tag contains the current source interfaces | [Deployment compatibility](../../../docs/technical/platform_infrastructure/deployment-compatibility.md) |
| How an operator verifies and installs the release | [Install on Google Cloud](../../../docs/getting-started/install-gcp.md#3-select-and-verify-a-release) |
| Guest image build project and pipeline | [GCP Guest Images](../../../docs/architecture/gcp-guest-images.md) |

Builds from `dev` or `deploy-test` are contributor test artifacts.
They do not establish production release or live deployment qualification.

## Rules

- One release serves every deployment. A new deployment needs no workflow or
  Environment change.
- A deploy-code fix needs a new release, because `gcp-deploy` requires that
  its own revision equals the release revision.
- Release from a ref that the workflow admits: `main`, `dev`, or
  `deploy-test`.
- A failed release scan is a finding to fix, not a gate to relax. Fix the
  image or the tool, open a PR to `dev`, and release again.

## Steps

1. Check that the release ref holds every fix that the cycle needs.
2. Start the release as [Publish a release](../../../docs/dev/gcp-contributor-deploy.md#publish-a-release)
   describes. For `dev` or `deploy-test`, dispatch it:

   ```bash
   gh workflow run release-gcp.yml --repo OpenRAE/bigrae --ref <release ref>
   ```

3. Wait for the run. Poll every few minutes, not every few seconds.
4. Read the deployer digest and verify the manifest as the procedure describes.
5. After the first release of a repository, ask the user to make the packages
   public.
