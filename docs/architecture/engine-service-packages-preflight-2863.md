# Engine service responsibility packages

## Status and scope

Architecture preflight for issue #2863 at revision `3b30e45f2`.
The supplied issue is the contract; no formal requirement is attached.
This record explains design constraints and the package map. It does not give an implementation sequence.

The checkout contains 100 implementation modules and one facade in `engine/services`.
All are below 500 lines; the RAES operation-result module is largest at 499 lines.
The issue's 128-module count describes an earlier state.
The `_model_*` family is absent after the [broker removal](../adr/068-model-access-broker-parked.md#removal-2909).
Do not restore that family or create an empty package for it.

## Package and dependency decisions

Use ordinary Python packages and explicit imports. No new library, loader, registry or dependency injection mechanism is needed.
Group existing responsibilities, then remove the redundant group prefix from each leaf module name.
For example, `_gcp_project/bindings.py` expresses ownership without a `_gcp_project_bindings.py` leaf.
The leading underscore marks package privacy; it is not a repeated responsibility prefix.

Keep responsibility packages private beneath `engine.services`.
Their small `__init__.py` files expose explicit interfaces for Engine code, not additional cross-layer APIs.
Retain `engine.services` as the external facade and preserve its declared `PUBLIC_API` inventory, signatures, defaults, return contracts and exception identities.
Preserve the existing compatibility exports in `engine/__init__.py` without allowing new callers to bypass the service facade.
Re-export existing DTO, enum and exception objects; do not recreate their definitions in package initializers.

This privacy decision matters to enforcement.
Both layer checkers permit public descendants of an allowed facade unless a symbol restriction applies.
A public `engine.services.range.authority` path would therefore broaden access for some domains.
An underscore-prefixed responsibility package preserves the existing private-component rejection without changing policy.
The canonical rules remain [ADR-001](../adr/index.yaml) and [the layer import configuration](../../scripts/check_layer_imports/layer_imports.yaml).

Use the existing import relationships and responsibility descriptions to establish ownership; filename similarity alone is insufficient.
These existing families must remain distinct:

| Responsibility | Boundary to preserve |
| --- | --- |
| Principal commands | Prepared authorization and commit fences; owner, initiating principal and executing workload are separate identities. |
| Range state and custody | SQL ancestry, ownership, generation and runtime projections establish facts, not permission grants. |
| RAES realization | Engine coordinates native realization; `shared.raes` owns released scenario interpretation and shared wire contracts. |
| Result application | Inbox admission, legal step ordering, typed payload application and transactional effects retain their separate responsibilities. |
| Artifact preparation | Grants, adapter admission, attempt credentials, workload evidence and materialization verification form the existing preparation workflow. |
| Runtime plugins | Tenant installation, pinned binding, isolated execution and accepted plans remain separate from preparation-worker grants. |
| Registered GCP projects | Registration, exclusive lease allocation, completion and release retain exact organization and operation custody. |
| Capacity, warm pools and disposable workers | Capacity assessment differs from reservation; warm generation differs from trial worker and its retention obligations. |
| VPN, terminal and device access | Provisioning authority differs from continuing session authorization and participant credential delivery. |
| Artifact acquisition and cleanup | Acquisition readiness differs from verified materialization, result success and verified absence after teardown. |

The package map follows the existing filename families:

| Package | Responsibility |
| --- | --- |
| `_capacity` | Capacity declarations, assessment, reservation persistence and per-range admission. |
| `_cleanup` | Cleanup outcome projection and provider readback evidence. |
| `_feature_artifacts` | Feature-artifact acquisition and launcher reconciliation. |
| `_gcp_project` | Registered GCP project registration, allocation, inputs, results, completion and release. |
| `_launch` | Launch authority, its local binding fences and cleanup authority. |
| `_operation_apply` | Operation-result admission, domain apply, effects and the RAES and VPN result families. |
| `_preparation` | Artifact preparation adapters, grants, operations, attempts, worker access and admission. |
| `_principal` | Principal-authorized range, NGFW, image, cancellation and warm-claim commands. |
| `_raes` | RAES range creation, bindings, image registry, evidence and status projection. |
| `_range` | Range authority, custody, ownership, placement, relationships and request-addressed lifecycle. |
| `_runtime_plugin` | Runtime plugin installation, binding, authority, operations, preparation and cleanup. |
| `_vpn` | VPN profile access, certificate operations, delivery, PKI results and session leases. |
| `_warm_pool` | Warm generation allocation, admission, retirement and recovery. |
| `_worker` | Disposable worker admission, trials, qualification, observations, software and retirement. |

A module whose name equals its family gets a name for its responsibility, for example `_range/compatibility.py`.
Singleton services without a family stay at the `engine.services` root.
Each package `__init__.py` re-exports only the names that the root facade consumes.
Engine modules import their dependencies from the owning leaf module, not from a package initializer.
This rule prevents package initialization cycles.

Apply the same ownership rule to launch, cleanup and other related helper families.
Do not create packages for unrelated singleton services merely to make the tree uniform.
Each module must have one responsibility. Do not merge a family into a large module to reduce the file count.
Keep shared dependencies at their current owning boundary; do not introduce a new catch-all `common`, `utils` or base service.

Existing precedents include `engine.models` for stable explicit exports and `shared.cloud.kubernetes` for focused implementation modules.
`shared.raes.__init__` demonstrates why package imports must avoid loading unrelated tooling.
Preserve function-local model imports, `TYPE_CHECKING` imports and deliberate import ordering.
Internal modules should use their owning implementation interfaces, not import the root facade during module initialization.
Retain the intentional call-time facade lookups in `_common`, `_range` and `_lifecycle`.
Those lookups preserve patchable secret retrieval and `transaction.atomic` behavior.

Do not replace them with copied bindings, wildcard exports, `sys.modules` aliases or runtime module discovery.
GCP registration and operation helpers already use call-time imports in both directions; eager package exports must not turn these dependencies into initialization cycles.
Keep pure range predicates and instance projection helpers in `engine._range_state`, where models and services can both consume them.

## Cross-cutting layers and security gates

Paths in this section are relative to `shifter/shifter_platform` unless stated otherwise.
The package change satisfies these layers by retaining the same objects, call paths, inputs and validation order.
It does not add another validation or authorization system.

| Layer and canonical incumbent | Required invariant |
| --- | --- |
| HTTP authentication and input shape: `config/_drf_settings.py`, `shared/api_tokens/authentication.py`, `shared/api/strict_json.py`, `shared/api/closed_serializer.py`, owning CMS and Mission Control serializers | Keep token scopes, session checks, closed request shapes and existing controller-to-service calls. Package exports confer no authority. |
| Business authority: `shared/credentials.py`, `shared/authorization/policy.py`, `shared/identity_scope.py`, `shared/range_access_authority.py` | Resolve current credentials and exact persisted ancestry before effects. Preserve original credential ceilings, revocation checks and bounded denial behavior. |
| Native command and dispatch fences: existing principal services, launch-authority helpers, `engine/launch_intents.py`, `engine/warm_activation_authz.py` | Preserve policy preparation, SQL rechecks, original intent and generation. Cleanup needs explicit bounded system authority, never a missing-actor fallback. |
| Cross-domain ownership: `workspaces.services`, `management.services`, `cms.services`, `config/credential_scope.py` | Keep scalar custody and sanctioned facade symbols. No cross-domain ORM imports, new tenancy schema, CMS pass-through or Engine dependency on presentation. |
| Typed input and output: `shared/schemas`, `shared/operation_envelope.py`, `shared/operation_results.py`, `shared/operation_intent.py`, `shared/raes/operation_input.py` | Reuse canonical parsers, versions and digests. Preserve discriminator, duplicate, conflicting-result, step-order and generation checks; do not recreate DTOs or wire schemas. |
| Worker proof: existing preparation admission/worker/workload helpers, `shared/preparation_grant.py`, `shared/artifact_preparation.py`, `shared/runtime_plugin_binding.py`, adapter SDK parsers | Preserve exact attempt, phase, expiry, signing salt, input digest, grant, executable pin and authenticated result binding. Compatibility success does not establish range readiness. |
| Deployment configuration: `config/settings.py`, its existing settings helpers, `engine/ecs/_config.py`, `shared/cloud` factories | Keep validated backend selection and existing settings projections. Do not replace them with new environment reads or confuse platform cloud with range backend. |
| Environment and OS exposure: `shared/cloud/sensitive_env.py`, `shared/cloud/kubernetes/_job_manifest.py`, existing task profiles and launch payloads | Preserve env key names, string shapes, Secret references, deterministic Job identity and command grammar. Put no token or payload in process arguments. |
| Runtime isolation: repository-root `platform/charts/shifter/templates/runtime-plugins.yaml` and `validatingadmissionpolicy-provisioner-jobs.yaml`; installed preparation profiles | Preserve fail-closed admission, exact image/service account, RBAC, restricted pods, network isolation and plugin sandbox. No adapter imports or installation in application processes. |
| Secret storage and retrieval: `engine/secrets.py`, `engine/field_encryption.py`, `shared.cloud.get_secrets_store`, existing plugin result encryption | Preserve reference-only projections, ciphertext formats, cache ownership and authorization-before-secret-fetch. Do not copy sensitive material into DTOs, logs or public projections. |
| Exceptions and public errors: existing `EngineError`, domain exceptions, `shared/exceptions.py`, `shared/errors.py`, `shared/api/errors.py` | Re-export the same classes; preserve catch behavior and authored public errors. Do not wrap every failure, expose provider messages or treat truncation as secret redaction. |
| Observability and audit: `config/_logging_config.py`, `config/logging.py`, `shared/log_sanitize.py`, `shared.audit` | Preserve event vocabulary, stable audit sources, attribution and strict audit placement. Retain bounded controller logs that report exception types without operation payloads. |

Moving a module changes a logger created with `logging.getLogger(__name__)`.
The existing `engine` logger configuration still captures descendants, but exact logger filters and assertions can change behavior.
Check existing consumers before changing names; preserve operational names where required, as `engine.ecs._config` already does.
Stable audit sources such as `engine.services.operation_apply` are event identifiers, not import paths to rename.

## Persistence and workflow boundaries

`engine.models` remains the ORM owner. Do not add repositories, tables, migrations or a second state machine for this refactor.
`engine/operation_inputs.py`, `engine/launch_intents.py`, `engine/retry_binding.py` and the existing public-operation services retain durable intent and retry ownership.
`engine/services/operation_policy.py` remains the existing durable-effect authority inventory, not a second workflow engine.
Input, launch intent, strict audit and domain changes retain their existing transaction relationship.
Result disposition, state changes and `RangeEventOutbox` publication remain atomic.

Preserve each workflow's lock order, lease fencing, retry bounds, cancellation rules and recovery scans.
In particular, warm result application locks the generation ledger before the runtime.
Preparation uses its scope, grant, adapter, operation and attempt fences; network calls remain outside the existing critical sections.
Preserve `on_commit` publication and dispatch, including the outer retry-binding transaction described in [range authority publication](range-authority-publication-2830.md).
Do not substitute direct queue delivery, early cloud dispatch or success flags for durable evidence.

Keep the provisioner contract independent of Engine implementation paths.
The provisioner consumes `shared` contracts and its restricted database projections; it must not import the new service packages.
Private pack content stays outside this repository. Use synthetic fixtures and the public adapter SDK.

## Whole-repository exposure and verification boundaries

Module moves affect absolute and relative imports, type-only imports, patch strings, direct internal tests and management-command imports.
`engine/apps.py` also imports the authorization inventory during Django startup.
The existing facade eagerly exposes services; deeper package initializers must not cause new startup queries, cloud calls or circular initialization.
Search current callers and maintained configuration across the repository.
Avoid compatibility files that recreate every old prefixed module.
Retain an old path only when an actual supported serialized or external contract requires it; document that exception before removing it later.

Update live path references in `docs/adr/index.yaml`, `docs/adr/documentation-coverage.yaml` and affected requirement traceability when their targets move.
An issue without attached requirements can still move code referenced by existing requirements.
Preserve historical records and applied migrations; they are not a reason to rewrite old evidence or restore removed code.
Check coverage source paths, mypy settings, Ruff configuration, Sonar exclusions and quality path routing for moved-file assumptions.
The routing owners are `.github/quality-path-filters.yaml` and `scripts/quality_ownership/classify_paths.py` at repository root.
`scripts/adr_guard/changed_python_quality.py` owns changed-line Python quality checks; reuse it without broadening exclusions.

The portal image copies the platform tree; the provisioner image copies shared contracts separately.
Package organization must not change that runtime separation or require image, Helm, IAM or deployment changes.

Use the existing checks, with no new enforcement framework:

- Repository architecture: `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
- Platform imports: `uv run lint-imports --config ../../.importlinter` from `shifter/shifter_platform`.
- Layer policy: `scripts/check_layer_imports/check_layer_imports.py` through its existing tool environment.
- Existing platform Ruff, mypy, Django startup/migration checks and Sonar S104/coverage gates through their configured lanes.
- Explicit changed-path writing checks from [CONTRIBUTING.md](../../CONTRIBUTING.md#documentation).

All production Python modules, including package initializers, remain within the 500-line limit.
Do not add Sonar exclusions, lint suppressions, coverage omissions or import allowances to make the reorganization pass.

Reuse behavior tests under `tests/engine/services`, `tests/engine/ecs`, `tests/cms`, `tests/config` and `tests/mission_control`.
`tests/engine/test_exports.py` checks compatibility exports at `engine`; it does not establish completeness of `engine.services.__all__`.
Verify service export identity and intentional late-bound hooks as well as successful imports.
Use existing PostgreSQL tests for locking, duplicate delivery, stale generations and rollback; SQLite cannot establish those guarantees.
Relevant suites include preparation, warm retirement/reservation, principal launch, runtime plugins, public-operation retries and result application.

Use focused mutation checks for any changed authorization or application branch; a path-only move does not justify changing those branches.
Full suites belong in CI, following [the testing reference](../dev/testing.md).

## Extensibility and non-goals

The extension seam is the owning responsibility package's explicit interface, with cross-domain consumers continuing through `engine.services`.
A future result family uses `shared.operation_results` contracts and the existing application dispatch.
A future backend uses current backend bindings, shared cloud factories and task-profile parameters.
Keep namespace, image, environment and workload identity in existing configuration/profile inputs; do not encode them in package names.
No new generic dispatcher, plugin registry, service container or configuration format is warranted.

This issue does not redesign authorization, schemas, exception hierarchies, storage, workflow state, cloud delivery or public APIs.
It does not revive retired model access, move scenario assets, create deployment resources or weaken quality gates.
Any necessary correction to behavior needs separate justification and verification; package grouping must preserve the current observable behavior.
