# Deployment and operations documentation boundary (#2806)

Architecture preflight, 2026-11-09. Inspected source revision:
`5954ab13763deaba52a257d4ed8bde5bb1402ea6`.
[Issue #2806](https://github.com/OpenRAE/bigrae/issues/2806) is the delivery contract.
No formal requirement is attached. This note is explanation for contributors.
It records design constraints, not an implementation plan or operational qualification.

## Decision and authority

Rewrite the operating instructions around the existing deployment interfaces.
Keep procedures, exact reference facts, infrastructure explanation, and bounded tutorials distinct.
Page purpose does not require a directory move.
Put prerequisites, authority, cost-bearing effects, and expected results beside the affected steps.
Include failure handling, rollback limits, and cleanup there too.
Keep host architecture, tool versions, connectivity, quotas, and optional model enablement explicit where required.

Reuse ADR-008, ADR-011, ADR-022, ADR-037, ADR-038, ADR-042, and ADR-069 through ADR-070.
No new ADR, runtime abstraction, schema, validator, or exception is needed.
The existing schemas, workflow guards, and runbook tests remain the executable architecture contracts.

The checkout includes #2804 through merge `5954ab137`.
Use its released documentation skill and existing checks described in [CONTRIBUTING.md](../../CONTRIBUTING.md#documentation).
The tooling issue owns documentation-check guidance; this rewrite must not create another tool or style guide.

The #2761 change is commit `5f9d5db3cecbac5b748b54eb2a52fa4eba971b90`.
Commit `8420fed55f0395ec977217c4083b619c1c96f5c3` subsequently removed `docs/technical/handbook/gcp-first-run.md`.

The authoritative operator entry is [Install on Google Cloud](../getting-started/install-gcp.md).
The [GitHub-less guide](../technical/handbook/gcp-github-less-deployment.md) supplies detailed lifecycle procedures.
Link to these authorities from contributor setup and operational references.
Do not recreate the removed page as another installation procedure.
Check incoming links and published URL behavior before making further moves.

GCP is the primary supported release path.
Retained AWS/EKS source and contributor procedures do not establish equivalent published-release support.
Legacy GDC configuration acceptance does not qualify live-fire containment.
Distinguish current support, contributor deployment, planned behavior, and historical evidence on each affected page.

## Corpus and source owners

Scope includes the two named handbook paths, `docs/ops/`, `docs/runbooks/`, and operational sections of `docs/dev/`.
It also includes `docs/technical/platform_infrastructure/`, operational `docs/technical/dev/` pages, and deployment sections of `docs/how-to/`.
Include infrastructure and image READMEs, bootstrap guidance, and deployment smoke guidance outside `docs/`.
Review mixed pages by section; include their maintained generator prose at its source.
Preserve vendor notices, legal text, quotations, and exact historical or generated evidence with narrow, recorded exclusions.

| Subject | Canonical source and existing checks to reuse |
| --- | --- |
| Installation configuration | `shifter/installation/loader.py`, `schema.py`, `registry.py`, `settings_gcp.py`, `settings_gcp_deploy.py`, and backend settings. Reuse `bigrae-config validate`, `doctor`, and the package's loader, schema, settings, and contract tests. |
| Public and generated contracts | `shifter/installation/contract/`, `publication.py`, `published_contract/`, and `runtime_inventory*.py`. Preserve exported contracts and immutable version snapshots. Reuse contract-check and runtime-inventory commands; do not hand-edit generated schemas or manifests. |
| GCP lifecycle | `scripts/bootstrap/gcp_cli.py`, `gcp_install.py`, `gcp_deploy.py`, `gcp_deploy_stages.py`, `gcp_rollout.py`, and `gcp_destroy.py`. Reuse `test_gcp_deploy_commands.py`, `test_gcp_deploy_stages.py`, and `test_gcp_release_gates.py` under `scripts/bootstrap/tests/`. |
| Bundle, identity, and recovery state | Bootstrap `gcp_inputs.py`, `gcp_config_store.py`, `gcp_identity.py`, `gcp_lock.py`, `gcp_terraform.py`, and `gcp_storage_cmek.py`. Existing tests include `test_gcp_inputs_store.py` and `test_gcp_process_identity.py`. |
| Runtime and Kubernetes | Bootstrap `gcp_runtime.py`, `gcp_control_plane.py`, `gcp_helm.py`; `scripts/gcp/render_runtime_env.py`; `platform/charts/shifter/`; platform `config/` env parsers and manifest generator. Reuse renderer, Helm-values, chart, and runtime-parity tests. |
| Releases and images | `shifter/installation/gcp_release.py`, bootstrap `gcp_provenance.py`, `gcp_oci.py`, `gcp_release_scan.py`, and `gcp_base_images.py`; `platform/deployer/gcp/Dockerfile`; release and Packer workflows. Reuse release-manifest, release-gate, workflow-guard, and image validation tests. |
| AWS and infrastructure recovery | Bootstrap `aws_eks.py`, `aws_native_identity.py`, `aws_env_destroy.py`, `account_recovery.py`, and `terraform_backend.py`; retained Terraform roots/modules and shared chart. Reuse AWS bootstrap/recovery tests and native Terraform tests. Derive resource names and state locations from the selected deployment. |
| Operational application tasks | Existing management commands, public service facades, and domain contracts own registration, content ingestion, authorization, retention, capacity, and range lifecycle. Follow each page to its actual owner and targeted tests. Registration and compatibility checks are not live qualification. |
| Smoke and incident handoff | `scripts/smoke-test*.sh`, `scripts/gcp/render_smoke_job.py`, bootstrap `gcp_smoke.py`, and `cms/post_deploy_smoke/` under the platform. Runbook structure and command safety belong to `scripts/adr_guard/tests/test_operations_runbooks.py`. |

The source inventory must include README files under `platform/terraform/`, `shifter/installation/`, and `shifter/packer/`.
It also includes `scripts/bootstrap/README.md` and `scripts/post_deploy_smoke/README.md`.
Distinguish local stack smoke from deployed range smoke; their prerequisites and evidence differ.
Use the tracked file set to record ownership and exclusions in the delivery PR.
The feature coverage manifest is not a complete migration inventory.

## Security and validation boundaries

These controls apply to the commands and examples that the rewritten prose instructs operators to use.
The rewrite changes no runtime gate.

| Layer | Required treatment |
| --- | --- |
| Config parsing and backend shape | Use `load_root_config`, the closed root/backend models, and shared policy validators. Preserve duplicate-key and YAML-merge rejection, secret-reference rules, field aliases, defaults, and cross-field conditions. A valid root config is not a complete deployment bundle or release-compatibility result. |
| Bundle and Terraform inputs | Preserve `gcp_inputs.py` object names, size limits, accepted store paths, and required Terraform values. JSON values follow HCL values; generated deployment-owned values come last through `gcp_terraform.py`. Keep the shared platform execution root, private `TF_DATA_DIR`, original backend prefix, provider locks, and separate foundation/runner state. |
| Cloud authority | Reuse `PurposeIdentities` and foundation IAM/WIF validation. Operators impersonate deploy, release-scan, and destroy identities; ambient credentials belong to the existing CI route. Preserve exact protected ref/workflow and immutable repository-ID trust. Cloud administration does not grant tenant application authority. Pin the operator account per command; do not change global gcloud identity. |
| Application authority | Native SQL duties, identity cutover, OpenFGA publication, and catalog bootstrap retain separate authority. Reuse bootstrap `gcp_identity_cutover.py`, `gcp_policy.py`, and `gcp_catalog.py`. Keep dedicated migration/publisher credentials separate from runtime credentials. Registration instructions must retain tenant scope, explicit permissions, and normal service validation. |
| Release admission | Preserve the manifest parser, tooling/release revision match, exact digest provenance, blocking vulnerability scans, and running-image readback. Reuse `gcp_provenance.py` and `gcp_release_scan.py`. Guest builds and validation occur in the build project; deployment imports verified publications. A tag, successful pull, mirror, or documentation build is not release trust. |
| Secret handling and host exposure | Keep secret values in provider stores and pass payloads through supported stdin, private files, or existing secret projections. `gcp_inputs.py` uses 0700 work directories and 0600 files. `ProcessRunner` uses fixed argv and suppresses sensitive streams. Do not add token/password literals to argv, shell tracing, command history, examples, logs, Terraform output, or PR evidence. Treat state and backups as sensitive. |
| Registry transport | `gcp_oci.py` sends Google credentials only to Artifact Registry hosts. Other registries use the existing anonymous pull flow. Mirror instructions must preserve digests and attestation referrers through `--release-source`; do not forward Google credentials to a mirror. |
| Env projection and runtime parsers | Reuse installation renderers, `runtime_inventory*.py`, bootstrap `gcp_runtime.py`, and `scripts/gcp/render_runtime_env.py`. The renderer receives an isolated environment. Preserve native identity checks, runtime role duties, `config/_runtime_env.py`, and the generated `config/env-manifest.json` contract. An arbitrary exported variable is not an operator configuration interface. |
| Kubernetes policy and network | Helm remains the renderer. `values.schema.json`, chart RBAC/NetworkPolicy, workload identity, and `validatingadmissionpolicy-provisioner-jobs.yaml` constrain jobs. Admission checks exact identities, images, literal/Secret env bindings, and executable fields. Do not suggest hand-built jobs, bulk `envFrom`, `kubectl exec`, disabled TLS, or admission bypasses as recovery shortcuts. |
| Errors, audit, and observability | Preserve `ConfigIssue`/`InstallationConfigError`, CLI `GcpCommandError` and native stage failures. Existing application `shared.errors`, `shared.log_sanitize`, structured logging, and `shared.audit` remain authoritative. CLI failures are not API error envelopes. Use bounded stage diagnostics and request/operation IDs; retain raw evidence privately through `gcp_evidence.py`. Public PRs contain synthetic, redacted results. |
| Writing and publication | Reuse `.vale.ini`, `.ste-required.txt`, the pinned local doc-tools package, Makefile targets, `vale.yml`, `docs.yml`, and `mkdocs.yml`. Keep dictionary checks and remote analyzers disabled. Preserve action pins, read-only PR jobs, secret scanning, and the separate Pages publishing boundary. Tool availability grants no authority for live operations, uploads, or publication. |

No controller, DTO, repository, database model, error hierarchy, telemetry store, or application endpoint is needed for this rewrite.
Do not import application internals into documentation tooling.
Keep private packs, adapters, image recipes, credentials, and acceptance evidence in their owning repositories.

## Operational gotchas

- Preserve RB001–RB024 names and URLs. Their required headings are `Symptom`, `Investigation`, `Resolution`, and `Prevention`, in that order.
  Their contract also requires escalation guidance and the exact `Read-only command:` label before shell examples.
  Do not evade command-safety tests by changing fence languages or disguising mutations.
  Route mutations to the authorized lifecycle or domain procedure.
- `gcp-install` creates the foundation and calls `gcp-deploy --first-install`.
  Do not replace this with copied Terraform, Helm, identity, or catalog orchestration.
  Automatic GCP OpenFGA publication does not remove the separate publisher duty or authorize runtime administration.
- Initial installation and normal updates have different DNS/certificate gates.
  Keep the first-install condition, required later certificate/readback checks, and bounded failure handling beside the affected action.
- `gcp-smoke` can create billable range resources.
  An empty smoke email skips it; deployment success does not then prove a range works.
  Status 3 reports advisory smoke failure after deployment.
  Request acceptance is not provider teardown completion; verify asynchronous cleanup and temporary Job/Secret removal.
- Atomic Helm rollback does not reverse data migrations, identity changes, published policy, or infrastructure changes.
  RB015 keeps migrations in the dedicated Job with the release digest and migrator identity.
  Preserve schema compatibility and data-owner approval for restore/cutover.
- `locks/deploy.lock` uses generation preconditions; a Terraform state lock is a separate lock.
  Stale-lock removal requires evidence that its owner is no longer active.
  Do not teach concurrent mutation, unconditional unlock, or deletion by guessed resource name.
- `gcp-destroy` requires the deployment name and leaves foundation resources, state/config/evidence buckets, keys, and other retained assets.
  State removal is not cloud deletion. Keep retention locks, residual costs, dependencies, and separate cleanup authority explicit.
- Availability, backup configuration, restore capability, and a dated recovery exercise are different claims.
  Preserve RTO/RPO targets as targets and observations as dated evidence.
  RB014 states that a fully qualified one-command GCP restore/cutover is absent.
  Do not invent that procedure or infer it from AWS examples.
- Check directory diagrams and configuration tables against the tracked source tree.
  The infrastructure index still contains Kustomize deployment language; the current GCP path uses Helm.
  Distinguish retained validation assets from an alternative deployment renderer.
  AWS recovery prose still mentions SSM cutover; verify it against native identity and EKS sources before presenting it as current.
- `bigrae-config` and `shifter-config` are both registered CLI names in `shifter/installation/pyproject.toml`.
  Naming cleanup must not rename internal paths, schema keys, compatibility identifiers, or exact historical commands by inference.

## Extensibility and evidence

The extension seam is the existing backend/profile selection, deployment bundle, and immutable release manifest.
Use deployment-owned parameters for project, region, name, hostname, operator, trust IDs, and image source.
Obtain resource identities from the selected deployment's outputs.
Another tenant must require new inputs, not edits to scripts or copied procedures.
Future release differences belong in versioned compatibility reference linked from the common task instructions.
The existing `.ste-required.txt` list enrolls rewritten pages without changing checker logic.

For representative install, update, recovery, and teardown paths, record evidence in the delivery PR.
Record source paths/revisions, release digest/revision where relevant, command checks, results, corrected differences, exclusions, and limitations.
Check supported release instructions against that release's source and manifest, not only the integration branch.
Check historical statements against their recorded revision; state when proof is absent.
Do not execute copied command blocks as a documentation test.

Authorized live GCP work must use the existing [operation skill](../../.claude/skills/gcp-tenant-operate/SKILL.md) and [release skill](../../.claude/skills/gcp-release/SKILL.md).
This preflight authorizes no live deployment, recovery, teardown, release, or data transfer.
Source inspection, CLI/parser checks, unit tests, rendered configuration, and live qualification are separate evidence classes.
Document their actual limits.

Run the configured Vale and STE checks on explicit changed paths, including off-site prose.
Review Diataxis purpose and technical meaning separately; three STE checks cannot establish full conformance.
Reuse targeted tests for affected contracts and leave full suites/corpus scans to CI.
Architecture guidance requires `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Executable changes would also require their stack-native checks; they are outside this documentation rewrite.

Preserve useful anchors and page URLs. ADR-038-R3 requires verbatim relocations distinct from prose rewrites.
MkDocs link and anchor checks use `info` severity, so a strict build alone cannot prove link preservation.
Review rendered headings, descriptive links, diagram text alternatives, and redirects when a published page moves.
Check keyboard access if navigation changes; color must not carry meaning alone.
Keep internal architecture guidance outside the published site and retain index reachability for published pages.

Non-goals are runtime fixes, schema/default changes, new validators or generators, workflow redesign, new restore automation, and broader provider support.
Do not add tools, skills, hosting, remote text processing, dictionary copies, or duplicate operating procedures.
Report discovered runtime gaps separately; describe absent behavior honestly within this rewrite.
