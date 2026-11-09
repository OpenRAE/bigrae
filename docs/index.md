# BigRAE documentation

BigRAE provides cyber ranges for authorized purple, red, and blue team exercises and CTF events.
Use the route that matches your task.

## Start here

1. Read [Get started](getting-started/index.md) to install or join a deployment.
2. Follow [Launch your first range](getting-started/quickstart.md) on an installed GCP tenant.

The current GCP install procedure requires a release with a verified deployer image.
The latest published release checked on 2026-11-09, `v4.1.1`, has no such image.
[Check release eligibility](getting-started/install-gcp.md#3-select-and-verify-a-release) before running deployment commands.
GCP and AWS backend source is separate from published-release and live deployment evidence.

## Use BigRAE

| Purpose | Destination |
| --- | --- |
| Tutorials | [First range](getting-started/quickstart.md): launch, inspect, and clean up a Linux exercise. |
| How-to guides | [Features](features/index.md) and [task guides](how-to/index.md): complete a known task. |
| Reference | [FAQ](reference/faq.md) and [technical contracts](technical/shifter_platform/index.md): find exact behavior. |
| Explanation | [Key concepts](getting-started/concepts.md) and [architecture](technical/architecture.md): understand objects and boundaries. |

Use the [scenario catalog guide](scenarios/index.md) to inspect installed content and realizability.
Use [pack installation](scenarios/index.md#install-a-content-pack) for administrator-approved content uploads.

## Deploy and operate on GCP

| Doc | Read this when |
|---|---|
| [Install on Google Cloud](getting-started/install-gcp.md) | You install a new deployment from a published release. |
| [GitHub-less GCP deployment guide](technical/handbook/gcp-github-less-deployment.md) | You need the full detail of the release, the bundle, install, update, mirror, and teardown. |
| [RB023: GCP deployment](runbooks/rb023-gcp-deployment.md) | An install, update, or teardown fails. |
| [GCP tenant standup gotchas](dev/gcp-tenant-standup-gotchas.md) | You hit a known deploy problem. |
| [GCP range-cell deploy](dev/gcp-range-cell-deploy.md) | You configure the GCE range backend and its images. |
| [Deployment configuration and recovery](dev/deployment-configuration.md) | You need how the deploy renders its Terraform inputs and recovers state. |
| [Native CTF scenario content](dev/ctf-scenario-content.md) | You are publishing and binding private, digest-pinned native challenges to a scenario. |
| [GCP event capacity profiles](ops/gcp-event-capacity.md) | You are scaling a GCP tenant for an event, running the p30 public-path gate, checking drift, or scaling down. |
| [GCP native identity](ops/gcp-native-identity.md) | You are enabling native SQL, separating policy administration or qualifying live renewal and authority. |
| [GCP range audit telemetry](ops/gcp-range-audit-telemetry.md) | You are changing GCP range flow, NAT, or Vertex AI audit logging, or reading the deploy readback. |
| [Operations runbooks](runbooks/index.md) | You are diagnosing or recovering a deployed BigRAE environment. |
| [Model-access operations design](ops/model-access.md) | You are implementing or reviewing planned model access, budgets, revocation, migration, and recovery under #681. |

## Develop and govern

| Section | Read this when |
|---|---|
| [Technical docs](technical/index.md) | You are developing the platform: setup, Terraform, CI/CD, architecture, and subsystem docs. |
| [Architecture handbook](technical/architecture.md) | You need the system context, components, authority, lifecycle, and package boundaries. |
| [Developer environment setup](technical/dev/setup.md) | You deploy a development environment from your own fork with GitHub Actions, on AWS or GCP. |
| [ADR enforcement](adr/README.md) | You need how architecture decisions are recorded and enforced in CI. |
