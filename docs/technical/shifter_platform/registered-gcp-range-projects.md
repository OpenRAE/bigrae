# Registered GCP range projects

Issue #2716 introduces Engine-owned project registration and retained range
leases. Registration, encrypted baseline capture and custody enforcement are
implemented in code. Native launch and preparation acceptance retain the selected
projects for retries and cleanup. The native IAM/Secret Manager runtime and independent readback are implemented
in the current change; live provider qualification is still pending.
Nothing in this page claims a tenant deployment or live acceptance.

## Native capture boundary

Provider secret-version reads accept only ASCII decimal project and version
identities beneath an explicitly owned secret. Payload decoding retains the
64 KiB byte limit. Scope, account, policy, payload and restoration checks remain
separate from node projection and keep the same retained identities and custody
transactions when their implementation is refactored.

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
The worker also validates the existing keyed image-profile configuration and
excludes every image-owning project, including machine-image projects, before
creating an inventory client. A malformed profile cannot remove an exclusion.

The worker uses Google's ADC transport against fixed official REST endpoints.
It reads project IAM with policy version 3, service-account metadata and IAM,
user-managed key metadata, Secret Manager resources and IAM, and version
metadata. Pagination and response bytes are bounded. A denied, redirected or
incomplete response fails capture; it never produces an empty inventory.
Baseline secret payloads and private service-account keys are never accessed.

Policy reads use each provider API's request contract (#2773):

| Policy owner | HTTP method | Policy version 3 option |
| --- | --- | --- |
| Project | POST | JSON request body |
| Service account | POST with no request body | Query parameters |
| Secret | GET | Query parameters |

The service-account request follows Google's
[IAM policy API](https://docs.cloud.google.com/iam/docs/reference/rest/v1/projects.serviceAccounts/getIamPolicy).
An unsupported request method fails capture; it cannot produce a partial baseline.

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
digest cross the operation boundary. Registration and ordinary envelopes retain
the 256 KiB bound. Native RAES plan inputs alone have an 8 MiB limit; their payload
parser still validates the complete closed contract. Result budgets are unchanged. Cleanup reads the retained bucket and generation,
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

Runtime preparation accepts content plugin pins and installed worker apparatus
pins through the shared parser. Both retain the original plan, executable digest
and operation identity. A worker apparatus with no native cloud resources
allocates no project lease. Completion validates both pin forms against the
same accepted preparation.

Each lease records its original provisioning operation. Cleanup recovers that
operation's immutable input, retaining its project and image references even after
registry configuration changes. Prepared workers apply values only to a local
execution copy and carry the same approved lease references into teardown.
References are bound to the original plan, range, request and organization; they
grant no adapter-selected cloud authority. Unreleased project custody blocks
range ownership and scope moves, including after VPN access is retired.

The worker admits native cloud families only after all project references,
original baseline identities, supported shapes and literal payloads have been
validated. It generates data-only Terraform for the pinned Google provider in a
private workspace, with encrypted GCS state under the lease UUID and native state
locking. No pack Terraform, adapter cloud credentials, guest key issuance or new
storage service is introduced. Provisioning and destruction use original retained
lease inputs; unsupported shapes fail before effects. An unaccepted preparation
still uses its explicit pre-effect cleanup proof.

Service accounts precede grants; reverse dependencies remove grants before
accounts. Independent inventory checks account unique IDs, names/display names,
secret create times, replication and versions, every policy and audit setting,
and payload equality only for new range-owned versions. Baseline secret values
are never accessed. Cleanup refuses changed resource incarnations and restores
project policy using its current etag, then compares the entire baseline.

A cloud node with no guest, image, hardware, topology or substrate constraint
retains its original completion identity without adding a VM. Guest observations
cover actual guests; the host admits cloud configuration only with proof bound to
the retained lease and accepted preparation. Global open-posture authoring and
large recursive authority limits must still be admitted by the pinned public RAE
planner; declaring support does not bypass that gate. Full-size public admission
is tracked in OpenRAE/rae#1885.

`shared.gcp_runtime_plan` explicitly exports the existing compilation, payload
selection and node-projection entry points. Node helpers live in
`shared.gcp_runtime_nodes`; existing imports through the plan module remain valid.

RAE 10.7.2 admits full-size native cloud authorities and preserves scalar-only
project delegation. Adapter preparation evaluates those authorities with the
same published `PLAN_AUTHORITY_LIMITS` profile. It retains every exact sibling
and closed collection, and refuses work beyond the fixed profile. The worker
accepts new plans only from that producer; retained 10.6.0 inputs remain eligible
for cleanup under the existing closed transport checks.

Required APIs are enabled before baseline capture. Their setup is not owned or
reversed by the range overlay. The worker needs project-scoped account create,
update/delete and IAM-policy permissions; Secret Manager create/version/access,
policy and delete permissions; project policy writes; and access to the existing
bucket's `raes/project-state/` namespace for state and locks. It needs no
organization-policy administrator role. Exercise key handling remains external.

The GCP portal IAM module supplies the storage grants (#2775). Only the
provisioner receives `roles/storage.objectCreator` for the configured assets
bucket's `raes/project-baselines/` prefix, and `roles/storage.objectUser` for
its `raes/project-state/` prefix. The first grant cannot overwrite or delete
baselines. The second supports Terraform state replacement and lock removal.
The existing bucket read grant supplies listing; neither new grant permits
writes to other assets or gives another workload these permissions.

Release requires the current native destroy result to be applied, the range to
be destroyed, the overall inventory to report verified absence without residuals,
and exact restoration proof for the original lease/baseline. The release update
and result disposition share the result transaction. Unknown or residual state
retains custody. Logical status changes and missing Jobs are insufficient.

Native RAES plan inputs have an 8 MiB operation-envelope budget (#2777).
The released planner records cloud declarations in resources and operations;
the complete input can exceed 4 MiB even when its declarations are valid.
Both the portal and provisioner use the same shared validator. Ordinary
envelopes and results keep their 256 KiB budget. Preparation approval still
checks the complete retained destroy envelope before any provider effects.

The [design](../../architecture/registered-gcp-range-projects-2716.md) describes
the native RAES intent, literal Content, provider overlay and readback boundaries
that complete this feature. Targeted PostgreSQL, contract and synthetic worker
tests establish the implemented boundaries; full CI and approved live qualification
remain separate evidence.
