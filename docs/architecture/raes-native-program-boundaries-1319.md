# RAES-native backend program boundaries (#1319)

Architecture preflight, 2026-11-03. The supplied #1319 title, body and acceptance
criteria are the delivery contract. This note connects existing decisions to
remaining work; it is neither an implementation plan nor delivery evidence.
ADRs 001, 024, 025, 030–032, 034, 039, 040, 043, 046, 056, 058 and 063 apply.
No new schema, abstraction, exception family or workflow is required.

Read the [current handbook](../technical/architecture.md),
[contract transition](../technical/handbook/scenario-contract-transition.md),
[hard-cut ADR](raes-migration-adr.md),
[contract-pair boundary](raes-contract-pair-adoption-2722.md) and
[external runtime boundary](external-scenario-runtime-design.md) together.
The ADR-032 `raes-plan-accessor-boundary/v1` model in
[`docs/adr/index.yaml`](../adr/index.yaml) remains the checkable architecture
contract. Historical inventories and triage retain their factual names and
evidence limits; they do not authorize a retired runtime or certify parity.

## Decisions and distinctions

RAES owns portable authoring, compilation and provisioning intent. Only
`shared.raes` imports its module family. CMS delegates pack validation and
canonical digest verification to `raes_env_packs` through
`cms.scenarios.pack_validation`. Engine owns native lifecycle and persistence;
the standalone provisioner realizes validated serialized plans as plain data.
Product callers use public service facades permitted by `.importlinter` and
`scripts/check_layer_imports/layer_imports.yaml`, never domain-table access.
Paths below are relative to `shifter/shifter_platform` unless qualified.
Launch stays in CMS `_scoped_range_launch` / `_raes_range_create` /
`_raes_dispatch`, through public `engine.services.create_raes_range`; retain
capacity/model admission, leases, deadlines and cancellation on that path.

| Fact | Authority and limit |
| --- | --- |
| Pack validity and identity | Upstream environment-pack validation and canonical content digest. Neither is authorization, executable-adapter installation or launchability. |
| Backend support | `shared.raes.manifest`, `contracts`, `realization`, `_runtime_target_envelope` and `composition_envelope`. Regenerate the published JSON from its builder; new upstream vocabulary cannot acquire support automatically. |
| Catalog assessment and admission | `cms.scenarios.realizability`, `shared.raes.realizability`, `package_loader` and `runtime_target`. Reuse the no-dispatch assessment port and common validate/interpret path. Capability, inventory supply and source integrity are separate contributors; `INDETERMINATE` is not realizable. Launch rechecks actual bindings and bytes. |
| Accepted work and completed work | A durable launch intent or enqueue receipt proves acceptance. `shared.raes.completion` admits independent resource/OS/composition observations bound to the immutable plan, RAES operation, Shifter generation and realization/configuration digests before READY. Synthetic completed dispatch proves protocol integration, not cloud effects. |
| Participant records and runtime support | `shared.raes.participant_runtime` stores reference-only product evidence. The current manifest is `provisioning-only`; sidecars, SSH/RDP access and Mission Control projections do not establish RAES participant lifecycle/history/evidence protocol support. Preserve the #1291 no-overclaim gate. |
| Destroyed and verified absent | `RangeCleanupVerification` and ADR-063 retain obligations until scoped provider inventory establishes `VERIFIED_ABSENT`. Failed or unavailable inventory is not empty success; cleanup evidence is not another lifecycle owner. |

The checked-in platform and Packer manifests pin the current released pair;
they and their locks, not this note, own version selection. Dependency release,
serialized plan transport, native operation envelope and HTTP API versions are
independent. Keep exact producer selection before payload access. The incumbent
`raes_plan_contract.prepare_envelope(cleanup_only=...)` preserves reviewed exact
older RAES pairs solely for cleanup, without rewriting their bytes or admitting
them to new realization. That is separate from removing the legacy RangeSpec
path and does not authorize retaining it.

## Cross-cutting layers to preserve

These are existing gates to pass, not additional validators to build.

| Layer and canonical incumbents | Required design behavior |
| --- | --- |
| Authentication and authorization: `shared.api_tokens.authentication`, `shared.credentials`, `shared.authorization`, `shared.identity_scope`, `workspaces.services`; CMS content-authority, custody and scoped-launch services | Preserve fail-closed bearer handling, session CSRF, credential ceilings, current policy checks, explicit organization/workspace/resource scope and admission reauthorization. A pack, a provider qualifier, staff status or a validation command cannot supply native launch authority. Authorize before sidecar lookup; unknown and inaccessible ranges remain indistinguishable. |
| HTTP and authored input: owning DRF serializers, `shared.api.closed_serializer`, `shared.api.strict_json`, `shared.raes.json_ingress`, `cms.scenarios.pack_validation`, `shared.schemas.raes_package_source` | Reuse each surface's closed field sets and bounded parser. Retain duplicate-key/non-finite JSON rejection where provided, UUID/digest/length checks and upstream SDL/import-lock semantics. Do not copy portable schemas into controllers, DTOs or provider modules. Process-boundary wire checks remain necessary even after producer semantic validation. |
| Filesystem and storage: `shared.raes.object_source`, `package_loader`, `cms.services._raes_dispatch`, existing `ObjectStorage` adapters | Preserve immutable-object preconditions, canonical digest re-verification, bounded downloads/extraction, path containment, link/special-file rejection, one direct SDL entry and private temporary-directory cleanup. No parser-triggered network import, dependency installation or unapproved storage destination. |
| Realization and containment: `shared.range_instantiation_policy`, `range_lifecycle_capability`, `range_cells`, `range_escape`, `remote_access`; provisioner `raes_gcp_plan`, `raes_gcp_apply`, `raes_ec2_runtime`, `raes_ec2_apply` and provider config loaders | Bind effects to the persisted backend, trusted purpose, request and resource generation. Preserve IPv4/address/reference, image, egress, subnet coordination, guest transport/host-key and independent readback gates. GCE live-fire containment is provider-enforced; GDC validation is not a participant fallback. Guest root is hostile; guest/model identity must never gain management or cross-range authority. Pause/resume requires support for the entire realized asset mix. |
| Immutable operation input: `shared.operation_envelope`, `shared.raes.operation_input` and binding parsers, `engine.operation_inputs`, `engine.launch_intents`; provisioner `provisioner_db_operation_input`, `raes_plan`, `raes_plan_contract` | Compose the persisted plan and existing bounded identity bindings. Keep exact keys, resource/request/operation equality, canonical digest, size bounds and generation fences. Reject unknown/malformed present values before mutation. Read by operation identity, never latest-by-request or mutable registry/domain tables. No second topology DTO, plan store or repository. |
| Secrets and bindings: existing cloud secret stores, `shared.field_encryption`, `shared.raes.artifact_binding`, `content_delivery`, `participant_access`, `shared.model_access` | Preserve field encryption, server-owned credential names, binding ownership and separate participant/management custody. Identity sidecars stay byte-free. Secret references are not credentials or permission to read arbitrary provider paths; signed URLs are secret material even if a field ends in `_URL`. Plan/payload confidentiality also requires controlled access; field-name checks alone cannot prove it. |
| Environment and configuration: `installation.schema`, `registry`, `runtime_inventory*`, `config._raes_settings`, `_product_env`, `_env_manifest`, `config/env-manifest.json`; provider renderers, entrypoints and task profiles | Keep one root-selected backend bundle and typed loader path. Any justified setting must agree across schema, environment inventory/manifest, renderer, deployment binding and consumer. No handler-local environment parser, retired selector or second provider registry. A new substrate belongs in `RANGE_BACKENDS`, not a new cloud bundle. |
| OS/process and Job exposure: `engine.launch_intents.validate_provisioner_command` / `command_from_payload`, `shared.cloud.sensitive_env`, `shared.cloud.kubernetes._job_manifest` / `_profile`, provisioner guest transports | Keep argv identifier-only and structured; no token, plan, runtime config or generated secret command in shell strings or process argv. Sensitive task env uses the existing Secret-reference path, never literal Pod env/ConfigMap values; check classifier precedence for any new key. Preserve non-root UID, read-only filesystem, dropped capabilities, seccomp, restricted service identity/network and cleanup of temporary secrets/files. |
| Results, concurrency and durable workflow: `OperationInput`, `OperationResultInbox`, `engine.services._operation_apply*`, `shared.operation_results`, `shared.db.operation_authority`, Engine subnet coordination, `RangeEventOutbox`, drainers and reconcilers | Retain least-privilege SQL grants, append-only producer results, ownership/order/digest/generation validation and transactional state/evidence/audit/outbox application. Retries reproduce stable observation timestamps; conflicting replay fails. Reuse `PublicOperationRetryBinding` for public retries. Transient handler failure must reach queue retry/DLQ; websockets remain advisory. No direct provisioner domain/outbox writes, second event bus or lifecycle ledger. |
| Sidecar persistence, audit and projections: `shared.schemas._raes_validation`, `raes_operation`, `raes_participant_runtime`; `shared.raes.operations`, `participant_runtime`, projection modules; `shared.audit` | Reuse shared bounded-reference, digest, timezone, secret-rejection and contract/profile validators plus model validation, uniqueness and conflict handling. Preserve source-time retention, redaction, bounded pruning and response allowlists. Operational sidecar expiry cannot discard immutable inputs or cleanup obligations. Security audit, authored audit declarations and scientific trial archives have distinct owners and retention; reuse their existing boundaries. |
| Exceptions and observability: existing `PackValidationError` / `PackDigestError`, `RaesPackageError`, shared `CMSError` / `ValidationError`, `RaesOperationInputError`, provisioner `RaesPlanError` / classified cloud failures; `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, provisioner `log_redact` | Translate foreign errors at the owning adapter into stable codes and curated public text. Use the canonical API envelope and accepted request correlation, with bounded validation details. Log safe counts, durations, states and operation identities; fingerprint sensitive references. Truncation, `safe_log_value` and secret-pattern rejection do not remove confidential content. Raw parser/provider exceptions, chained tracebacks, commands and payload dumps must not enter logs, audit, events, DLQs, reports or API details. No duplicate exception hierarchy or broad catch that turns failure into success. |

An existing output risk deserves explicit review: `run_raes_backend_validation`
currently calls `logger.exception` and wraps `str(failure)` with
`safe_log_value`. Object-source errors can also contain provider error text.
Those paths are not evidence that diagnostics are confidential. Acceptance
reporting must classify errors at the source and test secret-bearing failures;
shortening a message is insufficient. This preflight does not change runtime code.

Configuration owners include root `.shifter.yaml`, `shifter/installation/`
schema/registry/render/runtime-inventory modules, `scripts/gcp/render_runtime_env.py`,
`shifter/engine/provisioner/config/`, `platform/terraform/` and the single
`platform/charts/shifter/` chart. Runtime bindings must also satisfy cloud IAM,
SQL grants, Kubernetes admission and NetworkPolicy, not just a Python validator.
Platform/Packer `pyproject.toml` and `uv.lock`, their Docker build paths and the
platform's hashed GCP dependency overlay must stay consistent when touched;
do not add RAES to the standalone provisioner to share semantic validation.

## Legacy retirement and provider gotchas

`cms.services._raes_range_dispatch.create_range_dispatch` already launches RAES;
`RangeInstance.range_spec` is `None` for that path. Nevertheless, this checkout
still contains executable RangeSpec consumers. The #2554 boundary therefore
extends beyond deleting a schema:

- `shared.schemas.range`, `request`, `registry`, `engine.interpreter`,
  `engine.operation_inputs` and `engine.launch_intents` retain legacy shapes or
  command handling. Shared `InstanceSpec`, request/NGFW contracts, range-cell
  resource bindings and numeric `legacy_range_id` uses are not automatically
  legacy authoring; inspect their consumers before removal.
- CMS range queries/common projections, `ctf.bridges`, Engine terminal access,
  post-deploy smoke and capacity/warm-pool consumers must retain RAES behavior
  without hydrating the plan back into RangeSpec. Use public realized-guest and
  participant-safe projections, with their existing authorization.
- Standalone `terraform_ops`, `terraform_vars`, `gcp_range_cell_scenario`,
  `gcp_range_cell_plan`, `instance_orchestrator` and subnet-allocation helpers
  contain legacy consumers. Preserve helpers still used by native RAES and
  standalone NGFW/VPN operations; do not delete by filename or name match.
- Before removing an executable reader, prove there is no retained resource,
  active intent, replayable result/event or cleanup obligation requiring it.
  Use the existing drain/migration and release coordination. Never relabel old
  plans, purge obligations or leave a hidden fallback. Retire public fields/routes
  through ADR-040's generated OpenAPI, trusted baseline/retirement mechanism and
  generated consumers; do not edit snapshots just to silence compatibility gates.

Native EC2 implementation and tests now exist, but #2069 remains a separate AWS
verification obligation. Neither GCE results, old AWS Terraform tests nor shared
protocol conformance establish native EC2 parity. Provider family `aws`, backend
`ec2`, registry provider keys and historical asset-type identifiers are different
vocabularies; exercise their lifecycle/capability integration rather than renaming
them globally. GCE has no NGFW support. Do not quietly drop an authored required
effect or revive RangeSpec to make an unsupported combination launch.

The extension seams already exist: select admitted substrates through
`RANGE_BACKENDS` and the persisted binding; qualify provider effects through the
existing manifest/realizer configuration and provider adapters; resolve artifact
supply through the injected availability port; add participant profile/record
versions through `shared.raes.contracts` only with released conformance evidence.
Keep provider/configuration and exact cleanup-version selections explicit there,
not in product views, pack-name branches or a new mirrored vocabulary. Enum
iteration in `realization.create_shifter_realization_envelope` currently marks
every upstream concern realized; audit enum growth instead of inheriting claims.

## Evidence, workflow and non-goals

Reuse the manifest-publication, backend-conformance, participant no-overclaim,
plan/provisioner-parity, completion, operation-applier, authorization and secret
environment tests, plus existing provider lifecycle/cleanup tests. Extend their
negative cases for unsupported effects, stale generations, altered inputs,
conflicting replay and confidential diagnostics; use mutation testing where
practical. Contract conformance runs the released suite, not a local substitute.
CI ownership stays in `.github/workflows/_quality.yml`,
`.github/quality-path-filters.yaml` and the root Makefile. Targeted tests run
locally; full suites belong in CI.

Supported deployment validation uses the current `run_raes_backend_validation`
and post-deploy smoke/participant-access paths against registered synthetic
packs, including verified cleanup. The old `aces-cutover-evidence-1264.md`
commands refer to retired names/flags and cannot be used as current instructions.
GCP releases and tenant operation use `.claude/skills/gcp-release/SKILL.md`,
`.claude/skills/gcp-tenant-operate/SKILL.md` and ADR-070/RB023; retain release
provenance, scan, runtime-image and identity gates. Record evidence per supported
deployment/backend/profile; do not infer AWS acceptance from GCP hosting.

Keep `.ground-control.yaml` repository identity, `.gc/plan-rules.md`, ADR registry
and exceptions authoritative. Requirement status/traceability changes belong in
reviewed repository files; historical issue lists are not current delivery proof.
Architecture changes pass `python3 scripts/adr_guard/adr_guard.py --all --level ci`;
changes to imports, workflows, Terraform or Helm also pass their existing
stack-native checks. Do not weaken enforcement for retirement or conformance.
Retain `.pre-commit-config.yaml`, `.gitleaks.toml`, `.tflint.hcl` and
`.kube-linter.yaml` checks, action pinning, chart rendering and strict Kubernetes
schema/admission validation on affected surfaces.

This preflight implements no child issue, removes no runtime/schema/API, runs no
deployment and certifies no capability or provider parity. It adds no migration
selector, parallel SDL/DTO, validation engine, workflow, hosting service or
scenario-specific behavior. Private content, adapters, image recipes, guest
scripts and acceptance evidence remain in their owning repositories; public
fixtures and records use synthetic examples. Pack installation never authorizes
executable installation: retain explicit tenant-administrator binding, the
published adapter SDK and the isolated worker boundary.
