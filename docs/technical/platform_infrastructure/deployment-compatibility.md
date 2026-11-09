# Deployment compatibility reference

This reference separates published artifacts from current source interfaces.
Use [Install on Google Cloud](../../getting-started/install-gcp.md) for the installation procedure.
Use the [GCP handbook](../handbook/gcp-github-less-deployment.md) for detailed lifecycle tasks.

## Release availability

| Revision or artifact | Available behavior | Limit |
| --- | --- | --- |
| Published v4.1.1, `c04d53db89c522d7437f3f0b508379bb96eaa58b` | Earlier application source | No GCP deployer image or `gcp-install` interface |
| Integration source `5954ab13763deaba52a257d4ed8bde5bb1402ea6` | Deployer build, `gcp-install`, update, recovery diagnostics, and removal interfaces | Source inspection does not prove that a tagged deployer release exists or qualifies a deployment |
| A later approved tagged release | The interfaces and images in its verified manifest | Verify its source revision, deployer digest, provenance, and release-specific compatibility before installation |
| A `dev` or `deploy-test` publication | Contributor test artifact from an admitted workflow ref | Separate from a tagged release; requires explicit approval for the target deployment |

The latest published release checked on 2026-11-09 was v4.1.1.
Release availability can change.
Select an actual approved release; do not replace an unavailable release with an unverified source build.
An image tag or successful pull does not establish release trust.

## Deployment paths

| Path | Source contract | Status and boundary |
| --- | --- | --- |
| GCP release installation | `gcp-install` from the verified deployer image | Requires a release containing that image; no repository clone or GitHub account for the operator |
| GCP update or removal | `gcp-deploy` or `gcp-destroy` from the matching release | Deployment bundle, exact image verification, purpose identities, and deployment lock remain required |
| GCP contributor CI adapter | `_gcp-dev.yml` calls the same lifecycle | No GCP target is currently selectable in `deploy.yml` |
| AWS contributor deployment | `aws-dev`, EKS lifecycle, and shared Helm chart | Published AWS installation support is planned; retained source does not establish release qualification |
| GCE range cells | Default GCP range backend | Live-fire admission still requires policy, configuration, and containment verification |
| GDC VM Runtime | Explicit non-user validation purposes | No live-fire containment approval; RAES realization capability is a separate check |

## Configuration and recovery contracts

`bigrae-config` and `bigrae.yaml` are the current configuration names.
`shifter-config` and `shifter.yaml` remain compatibility aliases.
Conflicting root configuration files are rejected.
Internal Python paths and the `.shifter.yaml` operations policy retain their existing names.

The current GCP settings require native SQL authentication and OpenFGA.
Configuration acceptance does not prove effective IAM, credential renewal, or recovery.
See the [installation configuration reference](../dev/installation-config.md) for fields and validation.

An atomic Helm rollback restores the Helm release after upgrade failure.
It does not reverse database migrations, identity cutover, policy publication, or Terraform changes.
Application rollback requires schema compatibility.
[RB015](../../runbooks/rb015-database-migrations.md) covers migration failures and data-owner escalation.

`gcp-destroy` removes the platform resources and retains foundation resources, protected keys, unmanaged secrets, and imported guest images.
Retained resources can continue to incur costs.
The [teardown procedure](../handbook/gcp-github-less-deployment.md#tear-down) identifies the remaining resources.

## Evidence limits

Source inspection, parser tests, rendered configuration, and writing checks are source evidence.
They do not establish a working deployment, live containment, or a successful restore.
A skipped smoke is not range qualification.
An accepted destroy request does not prove provider cleanup.
Keep deployment-specific qualification evidence in the owner's private records.
