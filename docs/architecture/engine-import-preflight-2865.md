# Engine import boundaries (#2865)

This explanation records the architecture preflight for issue #2865 at revision `3b30e45f2` on 2026-11-24.
The issue is the delivery contract; no formal requirement is attached.
This document adds guidance only. It does not enable enforcement or establish that the refactor is complete.

## Findings and compatibility boundary

The current tree contains 825 function-local import statements across 108 engine files, including one migration import.
Ruff reports 824 with the platform configuration because that configuration excludes migrations.
The issue's count of 990 is historical; zero remaining imports is the acceptance measure.

All eight existing `.importlinter` contracts pass.
They restrict cross-domain dependencies; they do not establish that engine dependencies are acyclic.
An engine-scoped `acyclic_siblings` probe fails at both `engine` and `engine.services`.
One exact cycle connects `_operation_apply_raes` and `_operation_apply_vpn` through `RaesRealizedAccessError`.
Other cycles cross launch intents, authority checks, operation-input construction, local dispatch, and service collaborators.
Cycle-breaker suggestions identify dependencies to inspect; they are not permission to remove behavior.

`engine/__init__.py` eagerly imports `engine.services` during Django application discovery, before models can load.
Moving service model imports upward without changing that entry point can raise `AppRegistryNotReady`.
The root aliases have callers in ten repository test files, including explicit export assertions in `tests/engine/test_exports.py`.
No production root-function import callers were found in the repository.
The canonical cross-domain interface is already `engine.services` under ADR-001.
Retiring root aliases is the recommended boundary, but it changes an asserted import interface.
That compatibility choice requires explicit authorization under the issue's behavior-preservation condition.
Until resolved, do not silently remove aliases or substitute a hidden lazy loader.

Paths below are relative to `shifter/shifter_platform/` unless marked as repository-root paths.

## Dependency decisions

- Keep the Django application package safe to import before model population.
  Keep model discovery in `engine.models`, with its existing model exports, app labels, tables, and field definitions.
- Keep public service names and signatures in `engine.services` and its `_public_api.py` inventory.
  Implementation modules must depend on owning collaborators, not import their own facade for patched names.
  Tests must continue to prove the same behavior; patch-location compatibility must not dictate a cyclic production dependency.
- Reuse the existing neutral leaves before extracting another helper.
  `engine._range_state` already serves model and service callers without an upward dependency.
  `engine.handlers._audit` already prevents a handler-facade cycle.
- Move an existing shared definition to its lowest valid owner only when a real dependency cycle requires it.
  Preserve exception identity through re-exports where needed; do not duplicate `RaesRealizedAccessError` or change its rejection semantics.
  Engine-only helpers belong in engine; cross-domain contracts belong in `shared`.
- Separate pure command parsing from authorization, SQL reads, and dispatch.
  `launch_intents.validate_provisioner_command`, VPN command parsing, and worker-trial parsing already define the accepted shapes.
  Relocate or reuse those definitions rather than creating another parser, command schema, or operation registry.
- Keep startup registration after model population.
  `EngineConfig.ready()` currently binds the authorization inventory; `config.apps.PortalConfig.ready()` already owns cross-domain composition.
  Any relocation must preserve the existing resolver bindings and startup failure behavior.
  Config callers must use public services and the per-symbol allowances in `scripts/check_layer_imports/layer_imports.yaml` at repository root.
- Reuse narrow callable parameters where dependency inversion is necessary.
  `_operation_apply_raes.ApplyFailure` and the lifecycle dispatch helpers already demonstrate this pattern.
  Do not add a dependency container, callback registry, service locator, or general workflow framework.

## Enforcement boundary and extension points

Use standard Ruff and Import Linter features through the existing quality jobs.
The locked tools are Ruff 0.15.13 and Import Linter 2.11; pre-commit currently pins Ruff 0.15.18.
Both tool paths must apply compatible settings.
Keep PLC0415 scoped to engine; provider factories and other domains retain their separate initialization contracts.
Account explicitly for the existing migration exclusion, including `engine/migrations/0114_device_request_custody_guards.py`.
Do not claim whole-engine coverage from a check that skips that directory.

The standard `acyclic_siblings` contract supports `ancestors = engine` and recursive checking.
Its package ancestor and depth are the extension parameters; do not maintain a handwritten list of engine modules.
Sibling acyclicity does not detect every child-to-parent facade cycle.
Use exact-module forbidden contracts with `as_packages = False` and descendant wildcards for facade backedges where required.
Synthetic probes confirmed that sibling-cycle and facade-backedge mutations require these distinct checks.
Include ancestor package initialization and paths through other first-party packages in the dependency review.
Static contract success and successful cold startup provide different evidence; neither replaces the other.

Canonical enforcement owners are:

| Owner | Constraint |
| --- | --- |
| Platform `pyproject.toml` and `uv.lock` | Ruff settings, dependency versions, typing, and Python compatibility |
| Root `.importlinter` | Domain constraints and standard engine cycle contracts |
| Root `scripts/check_layer_imports/layer_imports.yaml` | Package classification, public interfaces, and per-symbol permissions |
| Root `.github/workflows/_quality.yml` | Existing blocking platform lint, type, import, security, migration, and test jobs |
| Root `.github/quality-path-filters.yaml` and `scripts/quality_ownership/contract.py` | Fail-closed routing; `.importlinter` already selects the platform jobs |
| Root `.pre-commit-config.yaml` | Lightweight Ruff checks; do not add repository-wide startup or graph scans to commit hooks |
| Root `scripts/adr_guard/`, `docs/adr/index.yaml`, and `docs/adr/exceptions.yaml` | Architecture policy, documented enforcement, and owned exceptions with expiry |

Do not weaken existing rules, add blanket `noqa` comments, or globally discard type-checking imports to make the graph pass.
Use module-level `TYPE_CHECKING` only for annotation-only references, preserving runtime schema resolution and type introspection.
Do not swallow import failures or use postponed annotations to hide a runtime dependency.
The platform runs Python 3.14; shared modules also run under Python 3.12 in other images.
Keep the existing syntax targets and locked runtime dependencies.

## Cross-cutting controls that must survive

Importing a definition must not perform its operation.
Keep SQL queries, provider construction, secret reads, policy calls, task launches, and background work at their existing execution boundaries.

| Layer and canonical incumbents | Required preservation |
| --- | --- |
| Credential and authorization: `shared.credentials`, `shared.authorization`, `shared.identity_scope`, `workspaces.services`, and services `_launch_authority*` | Preserve current credentials, registered actions, SQL-owned ancestry, revocation checks, and fail-closed authorization. Preserve policy-call placement relative to database locks. |
| Startup authorization inventory: `engine.apps`, services `_authorization_inventory`, and `shared.authorization.inventory` | Bind the same bounded resolvers after models load. Missing bindings must remain failures, never empty authorized results. |
| Input validation: `shared.schemas`, `shared.operation_envelope`, `shared.raes.operation_input`, `shared.worker_trial`, and `shared.vpn_pki` | Keep existing discriminators, closed fields, digests, versions, and parser failures. Do not replace typed contracts with permissive dictionaries. |
| Persistence and execution: `engine.models`, `operation_inputs`, `launch_intents*`, services `_operation_apply*`, and `shared.operation_results` | Preserve immutable inputs, exact operation generations, lock order, result disposition, atomic audit/outbox writes, retries, and cleanup obligations. |
| Persisted specs and secrets: `shared.schemas.persistence`, `shared.persisted_envelope`, `engine.field_encryption`, `shared.field_encryption`, and `engine.secrets` | Preserve encrypted fields, migration helper paths, cache bounds, secret-reference handling, and sanitized secret failures. Do not fetch secrets during import. |
| Configuration and environment: `config._runtime_env`, `config._cloud`, `installation.schema`, `installation.runtime_inventory*`, and `shared.cloud` | Consume the validated backend and existing role-specific environment shapes. Keep capability selection and provider clients deferred; add no environment variables or eager credential discovery. |
| Host and workload: `engine.ecs._env`, `_config`, `_local`, `_workload`, and the canonical launch-outbox command | Preserve validated command shapes, generation identifiers, workload identity, secret environment separation, and local-mode gating. Secret values must not enter argv, command logs, or workload projections. |
| Errors and observability: existing engine exceptions, `shared.cloud.exceptions`, `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, and `shared.audit` | Preserve exception classes, sanitized response envelopes, request correlation, audit strictness, and stable logger names such as `engine.ecs`. Do not expose provider errors or credential references. |
| RAES and executable adapters: `shared.raes`, `shared.runtime_plugin_binding`, and the isolated plugin worker | Preserve RAES import confinement, administrator authorization, and process isolation. Moving an import must not load private adapter code into the portal or provisioner. |

The local-dispatch cycle is particularly sensitive: `engine.ecs._local` currently imports the launch-outbox management command.
Any shared extraction must leave that command as an entry point around the same dispatch behavior.
It must not create a second launcher or bypass committed intent claiming, authorization, or workload checks.

## Evidence and non-goals

Preflight validation passed the full CI-level ADR guard and all eight current import contracts.
Four existing tests passed: the clean-checkout startup test and the three engine export tests.
The proposed engine cycle probe failed as expected against the current source.
Temporary synthetic fixtures passed when clean and failed after sibling-cycle or facade-backedge mutations.
These checks do not establish behavior preservation for the future refactor.

Implementation evidence must include fresh-process Django startup and model discovery, public exports, and targeted affected service tests.
Cover ASGI, WSGI, worker command discovery, and migration/build entry points without changing their environment requirements.
Reuse `tests/platform/test_clean_checkout_posture.py`, `tests/engine/test_exports.py`, existing launch/outbox tests, and affected operation-applier tests.
Keep database-lock and generation evidence in the established PostgreSQL lane; SQLite cannot establish those guarantees.
Keep full suites in CI. Negative probes must show that new local imports and cycles fail the real configured checks.
If enforcement files change, update the existing ADR enforcement reference in that delivery and run its required guards.

Non-goals are new product behavior, new runtime dependencies, schema or database changes, provider redesign, and repository-wide import cleanup.
Implementation scope is engine dependency structure, necessary startup/interface adjustments, standard enforcement, and regression coverage.
Do not introduce dynamic imports, `sys.modules` lookup, lazy module proxies, or blanket `apps.get_model()` calls to conceal dependencies.
Do not duplicate validators, exception hierarchies, authorization policy, operation workflows, or private scenario material.
This preflight does not implement imports, lint configuration, CI changes, or a new checker.

Standard-tool references: [Ruff configuration](https://docs.astral.sh/ruff/configuration/) and
[Import Linter contract types](https://import-linter.readthedocs.io/en/v2.11/contract_types/).
