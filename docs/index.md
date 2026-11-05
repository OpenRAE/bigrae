# BigRAE documentation

BigRAE is a self-service cyber-range platform for authorized purple, red, and
blue team exercises and CTF events. It installs on GCP from a published
release. AWS support comes in an upcoming release.

New to BigRAE? Start with [Get started](getting-started/index.md):

1. [Install BigRAE on GCP](technical/handbook/gcp-first-run.md).
2. [Launch your first range](getting-started/quickstart.md).

## Use BigRAE

| Section | Read this when |
|---|---|
| [Getting started](getting-started/index.md) | You are new and want the install path, the first range, and the key concepts. |
| [How-to guides](how-to/index.md) | You want step-by-step guides for specific tasks. |
| [Features](features/index.md) | You need details on agents, ranges, the terminal, credentials, NGFW, or CTF. |
| [Scenarios](scenarios/index.md) | You are running a specific scenario. |
| [Reference](reference/index.md) | You need the FAQ or support pointers. |

## Deploy and operate on GCP

| Doc | Read this when |
|---|---|
| [Install BigRAE on GCP](technical/handbook/gcp-first-run.md) | You install a new deployment from a published release. |
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
