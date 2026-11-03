# Registered GCP range projects

Issue #2716 introduces Engine-owned project registration and retained range
leases. Registration, encrypted baseline capture and custody enforcement are
implemented in code. Native launch and preparation acceptance retain the selected
projects for retries and cleanup. Scenario overlay realization and independent
provider qualification remain in development.
Nothing in this page claims a tenant deployment or live acceptance.

## Native capture boundary

The installation-authorized API queues `range-project/register` through the
existing `ProvisionerLaunchIntent`, immutable `OperationInput`, installed worker
identity and result inbox. Its request correlation is the registration UUID,
not a fabricated range request. Both dispatch and capture acceptance recheck the
original credential and `installation.manage_cloud_authority` decision.

The input fixes the selected project, organization, existing private bucket and
protected deployment and registered image projects. The worker independently excludes its current
control projects. Disabled/failed registrations with an accepted baseline use
`range-project/verify`, which compares fresh inventory with the original immutable
artifact before re-enabling. A retry never replaces an accepted baseline.
Canonical command validation and the provisioner Job admission
policy admit only the registration command; launched registration Jobs require
an operation UUID. No cloud role is added to portal or adapter processes.

The worker uses Google's ADC transport against fixed official REST endpoints.
It reads project IAM with policy version 3, service-account metadata and IAM,
user-managed key metadata, Secret Manager resources and IAM, and version
metadata. Pagination and response bytes are bounded. A denied, redirected or
incomplete response fails capture; it never produces an empty inventory.
Baseline secret payloads and private service-account keys are never accessed.

The existing worker identity needs metadata read permissions on the dedicated
project: `resourcemanager.projects.get`, `resourcemanager.projects.getIamPolicy`,
`iam.serviceAccounts.list`, `iam.serviceAccounts.getIamPolicy`,
`iam.serviceAccountKeys.list`, `secretmanager.secrets.list`,
`secretmanager.secrets.getIamPolicy` and `secretmanager.versions.list`.
Registration does not grant these permissions. Baseline object access needs
read and create on the existing private bucket's `raes/project-baselines/`
prefix; capture does not need object overwrite or delete.

## Artifact custody and retry

Two complete inventory reads must agree semantically before capture. The clear
baseline is limited to 1 MiB and encrypted with the existing field-encryption
primitive; ciphertext is limited to 1,500,000 bytes. A create-only object key
binds registration and capture operation. Concurrent or repeated capture keeps
the first object and reads it back; it never captures a later range overlay as a
replacement baseline.

Only the exact ciphertext hash, size, bucket, generation and semantic state
digest cross the operation boundary. The existing 256 KiB operation envelope
budget remains unchanged. Cleanup reads the retained bucket and generation,
checks the ciphertext before decryption, and verifies the original organization,
project identity, capture and lease. Changed current configuration cannot redirect
that read. Provider change tokens are excluded from semantic comparison;
resource identities, conditions, audit settings and nested authored values remain
significant.

## Exclusive custody and release

Migration 0120 freezes accepted project/baseline identities and lease custody.
A partial unique constraint allows one unreleased use per project. Active uses
cannot be deleted, and a new use cannot begin already released. Allocation locks
the Range then project rows in stable order, checks native organization scope,
and reserves all selected projects atomically. A replay retains its original
request, range, plan and lease identities.

Only admitted native launch and preparation acceptance allocate projects; reading
an input cannot reserve one. Concrete native scope references select registered
project IDs, and any stated project number must match. Preparation validates the
original RAES authority before allocation. Its sealed mapping, project references
and invocation result commit together, after validating the full future cleanup
envelope against the existing transport limit. A caught acceptance failure rolls
back all newly reserved projects.

Each lease records its original provisioning operation. Cleanup recovers that
operation's immutable input, retaining its project and image references even after
registry configuration changes. Prepared workers apply values only to a local
execution copy and carry the same approved lease references into teardown.
References are bound to the original plan, range, request and organization; they
grant no adapter-selected cloud authority. Unreleased project custody blocks
range ownership and scope moves, including after VPN access is retired.

Release requires the current native destroy result to be applied, the range to
be destroyed, the overall inventory to report verified absence without residuals,
and exact restoration proof for the original lease/baseline. The release update
and result disposition share the result transaction. Unknown or residual state
retains custody. Logical status changes and missing Jobs are insufficient.

The [design](../../architecture/registered-gcp-range-projects-2716.md) describes
the native RAES intent, literal Content, provider overlay and readback boundaries
that complete this feature. Targeted PostgreSQL, contract and synthetic worker
tests establish the implemented boundaries; full CI and approved live qualification
remain separate evidence.
