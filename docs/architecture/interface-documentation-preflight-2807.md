# Interface documentation boundary (#2807)

Pre-implementation guidance, inspected 2026-11-09 at revision
`5954ab13763deaba52a257d4ed8bde5bb1402ea6`.
[Issue #2807](https://github.com/OpenRAE/bigrae/issues/2807) is the contract.
No formal requirement is attached. This record is not implementation or delivery evidence.

## Decision and scope

Rewrite supported interface documentation through the existing documentation system.
Apply the [shared tool boundary](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/documentation-tool-adoption-2804.md) and
[contribution guidance](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md#documentation).
The checkout contains the #2804 tool configuration and explicit-path entrypoints.
This inspection does not establish its GitHub completion status.
Complete that prerequisite before the rewrite starts.

Existing decisions cover this work; no new ADR or runtime abstraction is needed.
Retain ADR-001/024/031/032/034 for service, scenario and ingestion boundaries.
Retain ADR-022/037/038/040/055/066 for coverage, provenance, publication, API, accessibility and authority.
The [ADR registry](../adr/index.yaml) and
[current-state handbook](../technical/architecture.md) define their current application.
Earlier preflights describe evidence at their recorded revision, not current support.

Own exact reference and scenario-authoring material listed in #2807.
The user-guide issue owns FAQ prose; the contributor issue owns support instructions.
Directory ownership does not transfer those sections to this issue.
Coordinate authoring and communication coverage with #2055 and SDK distribution claims with #2241.
Reuse delivered material; record remaining overlaps and normative conflicts in the PR.
Do not change a normative contract to resolve a wording disagreement.

## Contract sources and coverage

Paths in this section are relative to `shifter/shifter_platform/`, unless qualified.
Build the delivery inventory from code, then compare it with prose and rendered output.
Use a PR table with interface, documentation location, source revision, check, result and corrected difference.
Record absent or unverified behavior and narrow exclusions in that same evidence.
No new coverage database or generator is needed.

| Surface | Existing authority and consumer |
| --- | --- |
| HTTP operations | `config/urls.py`, `config/api_urls.py`, `config/account_admin_urls.py`, included URL configurations, views, serializers and permissions. Resolve route precedence before describing an operation. |
| HTTP publication | `shared/api/contract.py`, `shared/api/schema.py`, `config/_drf_settings.py` and `config/management/commands/api_contract.py` own `openapi/v1.json`. Frontend `gen:api` consumes that artifact. |
| CLI interfaces | Inspect each maintained `management/commands/` parser, service call, help consumer and command test. Include registration, conformance, image and verification tasks that the scoped pages describe. |
| Scenario authoring | `pyproject.toml` and `uv.lock` pin RAES and environment-pack contracts. `shared/raes/` adapts released RAES contracts; `cms/scenarios/pack_validation.py` delegates pack validation and digest identity. |
| Supported realization | `shared/raes/manifest.py`, `realization.py`, `runtime_target.py`, `pack_conformance.py` and their backend JSON artifacts describe admitted shapes. The independent provisioner validates transport and implements provider effects. |
| Public adapter SDK | Repository path `shifter/shifter_adapter_sdk/` owns both import namespaces, runtime, preparation, trial, model-access, guest and verification contracts. Inspect package metadata, exports and tests beyond the README. |
| Native CTF content | `shared/schemas/ctf_content_reference.py`, `ctf/content_bundle.py`, content resolution, hydration and refresh services own distinct reference, bundle and event-state contracts. |
| Signed receipts | `shared/receipt_validation.py`, `ctf/validators/`, CTF submission services and CMS/Engine receipt services own profile, transport, binding, redemption and revocation rules. |
| Platform domains | Management, Workspaces, CMS, Engine, CTF and Mission Control own their service facades and DTOs. Include referenced authorization, audit, model-access, operation and lifecycle contracts. |
| Public example packs | Repository path `shifter/environment-packs/` is canonical source. Portal Dockerfile copies and `cms/scenarios/inbox_packs/manifest.yaml` determine shipment and runtime references. |

Generated pages and OpenAPI alone cannot prove interface coverage.
The schema exclusion hook currently has an empty prefix tuple; CTF is included.
Its settings comment still describes the earlier exclusion.
Compare mounted routes, schema output, public SDK exports, CLI help and public schemas independently.
An unmounted prepared interface is not a supported endpoint.

Field definitions, bounds, defaults, permissions, errors and compatibility belong in reference.
Authoring, validation and integration procedures belong in how-to guides.
Link rationale as explanation. Preserve useful URLs and heading anchors.
ADR-038-R3 requires verbatim relocations; keep any necessary move distinct from rewriting.

## Security and validation boundaries

These are existing gates that examples and claims must satisfy, not new runtime work.
Paths retain the preceding section's convention.

| Layer and canonical incumbent | Required treatment |
| --- | --- |
| Credential admission: `shared/api_tokens/authentication.py`, `shared/api/principals.py`, `shared/credentials.py` | Describe verified bearer credentials or current native sessions. Preserve invalid-bearer denial and session CSRF requirements. Provider identity alone grants no application action. |
| Policy and scope: `shared/authorization/operations.py`, `shared/api_tokens/scopes.py`, owning services and `workspaces.services` | Use registered actions, current credential ceilings and SQL-owned ancestry. Staff flags, memberships, ownership, scopes and cloud IAM are distinct facts, not interchangeable grants. |
| HTTP and domain shapes: DRF serializers, `shared/api/strict_json.py`, `closed_serializer.py`, `shared/schemas/` | Describe actual required fields, unknown-field behavior, duplicate-key rejection and bounds per interface. Do not create documentation-only runtime DTOs or duplicate validators. |
| Pack and SDL admission: `cms/scenarios/pack_validation.py`, `shared/raes/json_ingress.py`, `package_loader.py`, `sdl_validation.py` and `realizability.py` | Preserve upstream validation, exact digests, contained paths, archive limits and import restrictions. Compilation, conformance, supply admission and live realization are separate outcomes. |
| Runtime binding: `shared/runtime_plugin_binding.py`, `shared/operation_envelope.py`, `shared/raes/operation_input.py` and provisioner `raes_plan_contract.py` | Preserve closed bindings, exact generation identity and envelope budgets. SDK acceptance does not remove stricter host limits or authorize provider effects. |
| Worker isolation: `shared/cloud/runtime_plugins.py`, Kubernetes Job builder and SDK `worker.py` | Use administrator-managed bindings and pinned worker images. Retain network isolation, UID/GID 65532, read-only root and bounded temporary storage. Packs cannot install executable adapters. |
| Secret and configuration shapes: `config/_product_env.py`, `_runtime_env.py`, `_env_manifest.py`, `config/env-manifest.json`, `_ctf_content_settings.py` | Match supported aliases, defaults and fail-closed startup checks. Reference catalogs use the protected deployment binding; no new contributor-tool setting belongs in the runtime manifest. |
| Host and process exposure: `shared/api_tokens/cli.py`, `shared/private_files.py`, `shared/cloud/sensitive_env.py`, `engine/launch_intents.py` | Use existing credential-file options where provided. The reader requires a regular file owned by the caller, with mode 0600, and rejects symlinks. Keep secrets out of argv, shell history and literal Pod environment values. |
| Receipt transport: `ctf/validators/_receipt_profiles.py`, `_receipt.py` and existing HTTP transport helpers | Keep server-selected HTTPS endpoints, DNS/TLS checks, no redirects, deadlines and byte limits. Participant content selects approved profiles and objectives; it supplies no callback credentials or endpoint. |
| Public errors: `shared/api/errors.py`, `shared/errors.py` and owning domain adapters | Preserve stable codes, sanitized messages, serializer-shaped details and accepted request IDs. Describe actual legacy response exceptions. Never copy raw exception or provider bodies into examples. |
| Logs and audit: `shared/log_sanitize.py`, `shared/audit/` and owning audit adapters | Reuse bounded categories, safe identifiers and existing correlation. Strict audit and redacted projections remain distinct from diagnostic logs. Publish no proof bytes, answers, keys or private operational evidence. |

External adapters use the public SDK; they do not import application services or models.
The separate verification API supplies opaque bindings and a bounded runner.
It is not the runtime-plugin worker protocol or the signed-receipt callback protocol.
Do not combine their discovery groups, capabilities, errors or evidence formats.

Persistence descriptions must retain owning services, transactions, constraints and generation fences.
Reuse existing idempotency, outbox/inbox and cleanup behavior; do not invent a documentation workflow engine.
Remote receipt verification precedes scoring locks; redemption repeats binding checks under locks.
Keep replay consumption and hydration receipts distinct from SDK preparation receipts and RAES operation receipts.

## Material hazards found

- Pack documentation contributes to pack identity and release inputs.
  For example, `smoke-linux/associated-artifacts.json` inventories `docs/concepts.md` and its provenance ledger.
  Other public packs also inventory their documentation.
  Resolve the issue's output-preservation constraint before rewriting those bytes.
  A pack revision needs the existing upstream artifact tooling and normal version, digest and conformance treatment.
  Never leave stale hashes, invent a hashing script, bypass validation or exclude all pack prose.
  Keep exact provenance and review evidence intact.
- `docs/technical/shifter_platform/index.md` still calls audit reads staff-session-only.
  `docs/technical/dev/api.md` describes current `PolicyAuditLogViewSet` and `installation.read_audit` authority.
  Verify the mounted controller and service policy before correcting each occurrence.
  Authorization docstrings can also retain superseded role wording; the text alone is not behavioral evidence.
- The SDK distribution version is `0.2.0`, while its exported `__version__` is `0.1.0` at this revision.
  Record that discrepancy; do not silently fix package behavior in a prose rewrite.
  Distribution version, protocol version, API version, RAES producer and cleanup compatibility are different identities.
  Neither a local wheel nor a publishing workflow proves a package is published.
- RAES pins are `11.0.1` and environment packs `7.2.3` at this revision.
  Read supported realization and cleanup compatibility from their current sources, not older adoption notes.
  Authoring support, advertised capability, runtime readback and live qualification require separate statements.
- Docstrings, serializer help and CLI help can change generated descriptions or tested output.
  Inspect consumers first and edit maintained prose at its source.
  Do not hand-edit `openapi/v1.json`, generated TypeScript, schemas or fixture bytes for style.
  If source prose necessarily changes generated bytes, report the output-preservation conflict explicitly before widening scope.

## Checks, extension seam and non-goals

Reuse `CONTRIBUTING.md`'s explicit-path Vale and STE commands for changed prose.
The three STE checks do not establish full language conformance or technical accuracy.
Review Diataxis purpose and meaning separately. Non-Markdown prose needs consumer-aware review, not invented Markdown extraction.
Add fully rewritten Markdown paths to `.ste-required.txt` through the existing migration gate.
Keep narrow exclusions reasoned and preserve legal text, quotations and generated evidence.

Retain `.vale.ini`, `tools/install-vale.sh`, the Makefile and `.github/workflows/vale.yml` as the tool entrypoints.
Retain `.github/workflows/docs.yml` for publication and `_quality.yml` with `.github/quality-path-filters.yaml` for existing CI routing.
Keep `.pre-commit-config.yaml` fast. `.ground-control.yaml` supplies repository workflow commands.
Reuse `scripts/adr_guard/adr_guard.py`, `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml` for architecture enforcement.
Guardrail changes require matching ADR documentation; no gate change is needed for this rewrite.

`make docs-build`, `mkdocs.yml` and `docs/requirements.txt` own local rendering.
The MkDocs configuration treats unresolved links and anchors as informational.
A successful strict build therefore does not establish valid links or redirects.
Inspect the affected output, heading order, descriptive links and diagram alternatives separately.
Check keyboard access if navigation changes; do not use color as the only distinction.

SDK and pack documentation outside `docs/` also needs its actual consumer checked.
Keep off-site maintained prose in the inventory; publication exclusions do not imply confidentiality.

Reuse contract tests under `tests/shared/test_api_contract.py`, `tests/shared/test_api_errors.py`,
`tests/shared/raes/`, `tests/cms/` and `tests/ctf/` for affected claims.
SDK tests cover isolated packaging, protocols, boundaries and reports.
Provisioner tests cover independent plan readers and guest effects.
Run only relevant local checks; full suites belong in existing CI lanes.
Never execute provisioning or remote callbacks merely to check documentation.
Record historical verification against its original source revision.

The extension seam is existing versioned contracts plus PR coverage evidence and `.ste-required.txt` paths.
A future export or backend capability extends its owning contract and tests, then its reference entry.
It does not require another schema, reference generator, error hierarchy or workflow.
Keep `docs/adr/documentation-coverage.yaml` for feature discoverability and source drift, not as a second interface inventory.

This preflight changes no product contracts, runtime code, tests, packs, release settings or workflow gates.
The rewrite authorizes no deployment, package publication, new hosting or external text processing.
Use synthetic examples and retain private pack material in its owning repository.
Do not revive CyberScript, add compatibility fallbacks, copy private internals or claim unverified support.
