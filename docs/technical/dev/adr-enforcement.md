# ADR Enforcement

This reference describes the repository's architecture checks, policy owners, and failure contracts.
The Local Usage and How To Add A Rule sections are how-to guides.
The checked-in registry, checker implementations, hook configuration, and workflows determine current enforcement.

## What Exists

The [model-access design for #681](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/model-access/index.md) is a historical record.
Issue #2909 removed the broker and its model-access control subsystem (ADR-068).

The current enforcement stack has six parts:

1. `docs/adr/index.yaml`
   Machine-readable ADR registry. Each accepted ADR lists the rules and the checks that enforce them.

2. `docs/adr/exceptions.yaml`
   Explicit exceptions. If a rule needs a temporary waiver, record it here with an owner and expiry. Do not leave the exception implicit.

3. `scripts/adr_guard/` (the `adr_guard` tool)
   Repo-native policy runner and the entrypoint for ADR conformance checks.
   `adr_guard.py` is the executable CLI entry point and compatibility facade; it
   bootstraps `sys.path` once and re-exports the internal `_guard` package. Each concern family has a module under `_guard/checks/`. Examples include `k8s_security.py`, `secret_hygiene.py`, and `deploy_workflow.py`. `cloud_identifiers.py` owns the AWS-shaped `no-live-cloud-identifiers` scan. `gcp_deploy_identity.py` owns its GCP chart-values complement, `no-live-gcp-deploy-identity`. Shared kernels are `_guard/_common.py` and `_guard/_workflow_model.py`. The former supplies `Violation`, repository/Git helpers, and exception filtering. The latter supplies the `_dw_*` workflow-as-data model.

 `_guard/_registry.py` owns `CHECKS` and `CHECK_LEVELS`; `_guard/_cli.py` owns argument parsing. The
   deploy-environment evaluator does not execute workflow shell. It removes
   comments, requires the exact reviewed router program, and models its outputs
   as data. Its branch-reference inputs remain compatibility-only parameters.


The `_guard` package uses relative imports and can be imported independently. The facade re-exports its public surface. `python3 scripts/adr_guard/adr_guard.py` and tests that load it by path remain supported.

`sonar.sources` in `sonar-project.properties` includes the package. The `adr-guard-tests` CI job runs it under `coverage` and uploads `scripts/adr_guard/coverage.xml` for changed-code analysis.

4. `.pre-commit-config.yaml`
   Fast local hygiene and secrets checks. Full architecture checks run in CI;
   changed-file cloud identifier checks remain local. The
   `sonar-rules-changed-lines` hook runs pinned Ruff rules through `diff-quality`
   for Python lines changed against `origin/dev`. It reports complexity,
   argument/return counts, documentation, type annotations and line length
   within the configured production source paths. It does not run tests or
   measure coverage, and does not replace the blocking SonarCloud gate.
   Its repository wrapper reads committed, staged and unstaged Git paths with
   NUL delimiters and supplies escaped literal paths to `diff-quality`. Source
   roots, exclusions and the 100% threshold remain unchanged. This avoids the
   tool's repeated recursive include expansion through ignored `node_modules`
   trees; those directories are not application quality inputs.
   The source roots, exclusions, Ruff rules and 100% threshold are one fixed
   policy in `scripts/adr_guard/changed_python_quality.py`. The wrapper accepts
   no external arguments: attempts to change refs, linter flags or scope fail
   before any subprocess. Its Git and quality commands use literal `origin/dev`, argument vectors, and explicit option/path boundaries. No CLI text is forwarded into either command.
   The wrapper's regression tests use standard-library `unittest`, as required
   by the Python 3.11 ADR test lane; they need no pytest dependency.

5. `.github/workflows/_quality.yml`
   CI enforcement. ADR conformance runs as its own architecture gate.

6. Existing ecosystem tooling
   - `import-linter` for Python package contracts
   - `actionlint` for GitHub Actions workflows
   - `TFLint` for Terraform linting, including GCP resources through `tflint-ruleset-google`. CI initialization supplies the job-scoped `github.token` as `GITHUB_TOKEN`. Plugin release lookups use the authenticated GitHub API allowance instead of the shared runner IP's unauthenticated limit.
   - `gitleaks` for new secret leakage detection
   - `helm lint` for Helm chart validation where files are templates rather than plain YAML
   - `kubeconform` for Kubernetes manifest schema validation
   - `kube-linter` for Kubernetes security and best-practice enforcement
   - `Checkov` for IaC security scanning (Terraform and Kubernetes)

There is also agent-specific wiring:

- `.claude/hooks/adr_guard_hook.py` runs the ADR guard after Claude edits files.
- `.claude/skills/adr-check/SKILL.md` provides a default workflow for ADR conformance work.
- `.claude/skills/architecture-review/SKILL.md` provides a repo-specific architecture review checklist.
- `AGENTS.md` gives Codex a repo-local policy file, including Ground Control project context for the `/implement` workflow. The GC project pointer (and matching `.ground-control.yaml` `project:` field) names the `shifter` project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`) with `CTF-*`, `PLAT-*`, `GEN-*` UID prefixes by subsystem; an earlier draft incorrectly pointed both at `aphelion` (a separate, unrelated project).
- `.ground-control.yaml` is validated as a whole by the Ground Control context reader, so an unrecognized key fails the entire file closed rather than being ignored: the reader returns `invalid_ground_control_yaml`, and `/implement` loses the project, SonarCloud, and plan-rules context along with the offending block. The `routing:` block accepts only `enabled`, `default_provider`, and `stages`. Routing is advisory under ADR-036. It records a stage capability tier for telemetry without selecting an executor. Remove stale routing keys instead of reinterpreting them.

Review controls:

The #2555 quality repair uses the existing path contract and workflow model.
Ruff enables security rules for the guard, ownership tooling and smoke helpers.
The integration branch's Bandit jobs also cover these tools and the three
inspection scripts. ShellCheck covers smoke and container scripts.
MCP lint jobs reject security warnings, and the shared package has a test-matrix
entry. The existing kube-linter job supplies blocking Kubernetes security policy.


Checkov's separate Kubernetes checks are a blocking gate under ADR-004-R11 (#2558).
Helm lint and rendered kube-linter checks run together, including when optional
tests are skipped. BuildKit and Trivy validate container build inputs. The hosted
guacd job proves non-root execution, drive permissions and listener readiness.


The unused root branding assets have been removed after a consumer search.
The user also retired the two unused vendor CloudFormation installers.
Their quality owner and identifier exception have been removed.

The `provisioner-locks` hook and provisioner CI job check that the image's Python
requirements match `uv.lock`. The default export must match the frozen uv export;
GCP packages present in `uv.lock` must have the same versions. The image keeps
its existing pip-based install from these hash-pinned exports. Use the documented
[uv export command](https://docs.astral.sh/uv/concepts/projects/export/) when
regenerating them. The Guacamole image job also tests direct and nested jar
replacement, including rejection when an expected archive or dependency is absent.

Bootstrap regression tests use process boundaries for the affected CLI and GDC
flows. Their legacy mock allowance decreases from 256 to 175. No new allowance
or exception renewal is part of this repair.

The BigRAE rename (#2555) preserves the existing gates. After the same-owner
repository cutover, the Sonar condition permitted only `Brad-Edwards/bigrae` with
the same immutable repository and owner IDs. The repository then moved to
`OpenRAE/bigrae` (#2660). The repository ID stayed, and the condition now
permits the `OpenRAE` owner ID.


Its expression-model tests deny the
old slug, a recreated slug, another owner and fork-origin PRs. Future GCP deployments use
one exact configured repository identity with the same purpose, Environment,
ref and workflow restrictions. Under the user's no-deployments decision,
no cloud-trust overlap or live migration is required. No cloud resource name
or state location is derived from branding.

GitHub's rename changes the default OIDC subject to include immutable owner and
repository IDs. AWS and GCP templates and AWS bootstrap must construct that
format from their explicit identity inputs. Canonical defaults use the observed
IDs. Other repositories supply their own IDs. The explicit legacy format selects
only the old subject shape; a policy never accepts both shapes as a fallback.
Existing audience, purpose, branch and Environment restrictions retain their scope.


The image-role guard requires exactly the `dev` and `main` subjects. It checks the selected prefix expression when a policy uses a shared prefix. It rejects wildcards, extra subjects, and changed owner or repository ID fields.


The pinned Checkov action loads a version-bound compatibility adapter for the
immutable repository subject syntax. The adapter changes only the repository
parser; CKV_GCP_125 and the native WIF guard remain blocking.

CI parity checks
require the adapter path, and tests reject unsupported versions and parser changes.

Plugin admission accepts exactly one invocation key, `BIGRAE_PLUGIN_INPUT` or
its legacy alias, through a matching Secret key reference. The static and Helm
policies share the same restriction and behavioral admission tests. Settings,
installation and MCP policy aliases reject conflicting inputs at their owning
parsers; package aliases re-export existing contract types. Both compatibility
distribution roots remain owned by Dependabot. Local source validation does not
prove a live repository, publisher or workload-identity cutover.

- `.github/CODEOWNERS` requires review on guardrail files and shared/public architecture seams.
- `.github/pull_request_template.md` requires an ADR impact section on PRs.
- `.github/copilot-instructions.md` now points GitHub Copilot toward the same ADR enforcement model.
- `.ground-control.yaml` binds synchronized `/implement` runs to the root
  `make test` completion boundary. `make policy` runs ADR guard, import-linter, whitespace validation, and Vale against Markdown committed since `origin/dev`. Its documentation setup installs the pinned Vale binary and shared package through `tools/install-vale.sh`. The installer
  verifies the release archive SHA-256 before extraction.
- Local commits run file hygiene, secret scanning, cloud identifier checks, commit-message policy, Ruff, ShellCheck, actionlint, and Terraform formatting. They also run changed-line Python quality checks and the configured fast architecture and security guards. CI runs full tests, coverage, type checks, Django checks, import checks, and ADR checks. It also owns package-wide JavaScript/CSS lint, Checkov, Bandit, Terraform validation, TFLint, and Kubernetes/chart validation. These checks are removed
  from the commit hook, not moved to push hooks. This supersedes older references
  to local hooks for those checks; their policies and CI gates remain in force.
  `workflow.precommit_command` remains `pre-commit run` for staged-file hygiene.
  Run targeted tests directly during development. `pre-commit run --all-files`
  checks the hygiene baseline only.
- CI's quality-path-ownership contract (`.github/quality-path-filters.yaml`)
  remains the authoritative lint, security, and test matrix. Checkov's invocation
  guard requires the blocking CI scan with the canonical config and external
  module loading. A local Checkov hook is optional; if reintroduced, it must
  match the CI policy. Missing CI coverage or soft-fail still fails the guard.
- The `shifter_platform` pytest worker cap (`--maxprocesses` in
  `shifter/shifter_platform/pyproject.toml` `addopts`) is 8. Because `-n auto`
  already limits workers to the host core count, this cap only takes effect on
  hosts with more cores than the cap: CI runners with at most four cores retain core-count workers. Larger development and CI hosts can use the additional parallelism during explicitly requested runs. The cap also bounds peak memory because each worker loads Django. Increase it only with measured memory headroom, given the documented exhaustion history.
- CI runs the broad platform suite once against PostgreSQL, split into six
  `shifter-platform-tests` shards. Each shard publishes coverage data and its
  PostgreSQL marker evidence. `shifter-platform-coverage` requires all shards and rejects missing or duplicate evidence and skipped PostgreSQL-marked tests. At least one PostgreSQL-marked test must run across the shards. It combines the data, enforces the unchanged 87% package floor,
  and publishes `coverage.xml` for SonarCloud. Redis integration and adapter SDK
  packaging retain their own blocking jobs. Released OpenFGA/PostgreSQL tests run in their mandatory job and contribute `coverage-openfga.xml`. Native browser and built-image smoke gates retain real service and image entrypoints. Sharding changes execution cost,
  not the required evidence or coverage thresholds. Full suites and image
  smoke run in CI; local development uses focused regressions.
- `.github/workflows/_gcp-dev.yml` is a thin wrapper over the GCP deploy
  commands (ADR-070). The deploy renders each image by its
  exact digest from the release manifest, so a mutable tag never selects a
  running image.

Deploy-time enforcement (ADR-035):

- `scripts/bootstrap/preflight.py` is a shared, fail-safe deploy preflight. It is
  the single source of truth for deployment prerequisites (tools, secrets, config)
  and runs the same checks locally (the deploy CLI runs it at the start of
  `bootstrap`/`terraform`/`full`, and `deploy.py preflight` runs it on demand) and
  in CI (each reusable deploy workflow runs `python -m preflight` before any
  Terraform apply). It reports all missing prerequisites before execution. Skips are explicit and logged through `SHIFTER_SKIP_OPERATOR_BOOTSTRAP`, never silent conditional omissions. This
  is a runtime gate rather than an `adr_guard` static check; `docs/dev/deploy-secrets.md`
  and the spec are kept in step by the parity test in
  `scripts/bootstrap/tests/test_preflight.py`. For GCP, `deploy.py preflight
  --cloud gcp` validates the deployment input bundle (`--store` or `--inputs`)
  with the same loader that `deploy.py gcp-deploy` uses (ADR-070).

Documentation site (ADR-038):

- Documentation is authored as Markdown under top-level `docs/` and published as a
  single public mkdocs (Material) site on GitHub Pages by
  `.github/workflows/docs.yml` (`mkdocs build --strict` gates PRs; pushes to the
  default branch publish). Internal design notes, machine registries, and scratch
  dirs stay in-repo but are excluded from the published site via `mkdocs.yml`
  `exclude_docs`. The in-app Django documentation app is retired. This is a
  runtime/build gate, not an `adr_guard` static check.

Migration state (CI gate):

- Django models and their committed migrations must stay in parity. The
  `shifter-platform-lint` job in `.github/workflows/_quality.yml` runs
  `manage.py makemigrations --check --dry-run` (with `TESTING=1`,
  `TEST_DB_BACKEND=sqlite`, `DJANGO_DEBUG=true`, and a synthetic CI-only
  `DJANGO_SECRET_KEY`) as a blocking step. The command runs globally with no
  app-name arguments, so `INSTALLED_APPS` is the coverage seam and new Django
  apps are gated automatically. `--dry-run` writes nothing and needs no
  database, so a model change that is not captured by a committed migration
  (including database-neutral drift such as `help_text` or model manager
  changes) fails the job. This is a CI gate, not an `adr_guard` static check,
  and it mirrors the `api_contract --check` drift gate in the same workflow.
  Added by issue #1061.

## Current Checks

The first slice intentionally stays small:

- `adr-registry`
  Validates the ADR registry and exception files. It also validates the closed
  typed interface contracts required by ADR-032, ADR-039, ADR-051, ADR-054, and
  ADR-055. The `raes-plan-accessor-boundary/v1` contract pins the RAES-free standalone consumer, ownership, and validation boundaries. It requires rejection before mutation, full canonical address fallback, exact-pin compatibility evidence, and decision-only scope for #1937. The `dedicated-customer-authority/v1` contract protects ADR-054's customer boundary and authority separation. It also protects the event-migration gate, infrastructure ownership, outage behavior, and evidence classes. Removal or weakening fails locally and in CI. The `accessibility-enforcement/v1` contract pins the WCAG target, one axe/Playwright toolchain, and every-PR/nightly/deployed cadence. It also pins surface reconciliation, exact finding reduction, manual evidence, central waivers, and the security boundary. This is structural enforcement
  of accepted decisions, not a substitute for their runtime, migration, IAM,
  network, browser, or manual-audit tests.

  ADR-055's exact section values live in `ACCESSIBILITY_FIXED_SECTIONS`, with
  closed string collections in `ACCESSIBILITY_STRING_SET_SECTIONS`. Extend the
  contract table, registry entry, and mutation test together; do not add a new
  branch of repeated per-section validation.

  The registry check keeps contract support, specialized ADR contracts, and
  dispatch in separate modules. This preserves the closed contract surface
  while keeping each validator independently reviewable and within the static
  analysis limits enforced for guardrail code. Validator helpers have concise docstrings. The documentation check stays below the enforced file-size limit so SonarCloud can analyze guardrail changes on every PR.

- `layer-imports`
  Enforces the existing cross-layer import policy from `scripts/check_layer_imports/layer_imports.yaml`.
  Every first-party Django app is classified there (ADR-001-R3, #1523) as a
  domain (`engine`, `cms`, `management`, `ctf`, `workspaces`), presentation
  (`mission_control`), support/contracts (`shared`), or support/composition
  (`config`) layer. `workspaces` is the organization/workspace tenancy domain
  added by ADR-046 (#1325); other layers reach it only through
  `workspaces.services` and carry a scalar `workspace_id` rather than a
  cross-layer ForeignKey. Service-package imports may use only the public facade (for
  example `cms.services`); private split-package submodules such as
  `cms.services._range_pause` are not cross-layer seams. This covers `import cms.services._range_pause` and `from cms.services import _range_pause`. An AST pass detects the latter because the regex scan sees only the facade path. The rule exists in ADR guard, `scripts/check_layer_imports/check_layer_imports.py`, and `management check_model_fks`. Tests require their package lists to equal the canonical classification. `.importlinter` adds package-level enforcement. `shared` remains the freely importable
  contracts layer.

- `installed-apps-classified`
  Fails closed when an installed first-party Django app lacks classification in `layer_imports.yaml`. It also rejects stale classifications without a local `AppConfig` and dynamic `INSTALLED_APPS` expressions that cannot be statically resolved. This enforces ADR-001-R3 (#1523).
  The retired `documentation` package (ADR-038) has no `AppConfig` and is not
  classified.

- `guardrail-docs`
  Requires guardrail changes to update ADR or developer docs in the same change.
  This is a changeset-level check (needs to see multiple files) so it runs in
  pre-commit and `--level fast`, but NOT in the per-edit Claude hook.

- `no-agent-attribution`
  Rejects AI/agent attribution markers in tracked text (agent `Co-authored-by`
  trailers, Cursor marketing footers, Claude Code branding strings, etc.).
  A `commit-msg` pre-commit hook blocks the same markers in commit messages.
  When a commit is rejected for attribution markers, disable Cursor commit/PR
  attribution in `~/.cursor/cli-config.json` only; project `.cursor/cli.json`
  cannot set attribution (permissions-only per Cursor CLI docs).

- `cross-layer-model-imports`
  Fails on direct cross-layer model imports inside service layers. The current tree already satisfies this rule, so it is part of the default guard.

- `python-complexity-gate`
  Enforces ADR-012-R1: each canonical Python `pyproject.toml` must enable Ruff `C901` in `[tool.ruff.lint].select`. `[tool.ruff.lint.mccabe].max-complexity` must match `PYTHON_COMPLEXITY_THRESHOLD` in `scripts/adr_guard/_guard/checks/complexity.py`. The current threshold is `15`, matching SonarCloud's default cognitive-complexity threshold. `ignore`, `extend-ignore`, and `per-file-ignores` must not silently disable the rule. The check also
  cross-verifies that `PYTHON_COMPLEXITY_GATE_PYPROJECTS` matches the
  `id: ruff` hook working directories in `.pre-commit-config.yaml`, so
  a new lint surface cannot be added in one place without the other.
  Standalone verifier scripts under `scripts/` that ship their own
  `pyproject.toml` (for example the post-apply deploy checks such as
  `scripts/assert_portal_inspection`, added for issue #932) are gated
  surfaces too: registering one means adding its directory to both
  `.pre-commit-config.yaml` and `PYTHON_COMPLEXITY_GATE_PYPROJECTS` in
  the same change.
  The complexity computation itself is Ruff's job; this check is the
  config-shape backstop against silent gate removal. Existing
  high-complexity functions carry per-function `# noqa: C901`
  exemptions; the function-level backlog (one row per exemption with
  current complexity) lives at `docs/adr/complexity-backlog.md`. The
  threshold ratchets down as that backlog shrinks; a ratchet edit
  updates `PYTHON_COMPLEXITY_THRESHOLD`, every canonical
  `pyproject.toml`, and the backlog rows in a single PR. Runs in both
  `fast` and `ci` levels.
  `scripts/adr_guard/tests/test_adr_guard.py` exercises silent bypass and prefix-selector cases through `subTest()` loops. A new bypass shape, such as an `extend-select` variant, adds a row to the case tuple instead of another test method.
  The `uat/event-load-harness` UAT load harness (#926) is a registered
  package under this gate, with matching `Lint`/`SAST`/`Tests
  (event-load-harness)` jobs in `.github/workflows/_quality.yml`.

- `boundary-mock-policy`
  Enforces ADR-019-R1: new Python tests may patch real process, network,
  cloud, and framework transport boundaries, but must not add new
  first-party internal callable patch targets. The check statically parses
  tracked test files for `patch()` / mock `.patch()` string targets and
  statically resolvable `patch.object(imported_module_or_class, ...)`
  calls, then compares `(test file, target)` counts against
  `scripts/adr_guard/boundary_mock_baseline.json`. The baseline records legacy internal patches without requiring a complete test rewrite. Allowed counts may shrink but must not grow. The check compares the baseline with the branch reference. Increased allowances violate policy unless covered by a dated ADR exception. Prefer behavioral assertions, in-memory fakes at service boundaries, and real framework clients. Do not patch first-party service functions, views, rendering/logging/transaction aliases, or model helpers. Issue #202 removed the expired bootstrap exception through explicit CLI, Terraform, and GDC ports. The repository baseline decreased from 618 to 465 internal patches. No replacement exception was recorded.

- `documentation-coverage`
  Enforces ADR-022-R1 (GEN-001): every major platform feature listed in
  `docs/adr/documentation-coverage.yaml` must declare at least one user doc and
  at least one technical doc. The check validates the whole manifest on every
  run (it ignores the changed-file list, like `adr-registry`): each referenced
  doc must exist under the configured documentation tree (`docs_root`), must not live under a
  `_deprecated`/hidden path, and must be reachable from an `index.md`. This
  keeps the GEN-001 contract from silently regressing (for example, when a
  feature's doc is removed but its index link is left dangling). Adding a major
  feature means adding a manifest entry pointing at its user and technical docs.

- `published-contract-snapshots-immutable`
  Enforces ADR-011-R8: the published backend-bundle contract's per-version
  snapshots (`shifter/installation/published_contract/backend-bundle-contract.v<N>.json`)
  are append-only. Each snapshot records the frozen shape of a published contract
  version; a contract change ships a *new* version snapshot instead of editing an
  existing one. The check compares snapshots at the base-branch merge base with the working tree. Modifying or deleting an existing snapshot fails. This prevents silently replacing the compatibility oracle. Like
  `boundary-mock-policy` it resolves the base ref from `GITHUB_BASE_REF` /
  `ADR_GUARD_BASE_REF` (falling back to `origin/dev`/`origin/main`). It fails **open**
  locally (a shallow clone with no base history cannot compare, so dev is not blocked)
  and fails **closed** when `ADR_GUARD_SNAPSHOT_ENFORCE` is set: `adr-conformance` fetches complete base history with `fetch-depth: 0` and sets that variable. Failure to resolve or read the base then fails enforcement. A
  genuinely absent directory at the base (a real first publication) is distinguished
  from an unreadable tree and still passes.

- `accessibility-baseline`
  Enforces ADR-055-R4/R6: the browser-accessibility exact-finding baseline
  (`shifter/shifter_platform/frontend/e2e/a11y/baseline.json`) may only shrink.
  The committed fingerprints must be a subset of the trusted base baseline. New fingerprints require an exact-fingerprint ADR-055 waiver in `docs/adr/exceptions.yaml`. The central exception schema validates the optional `fingerprints:` list. Do not overload `paths` or `checks` for fingerprints. Each fingerprint is the
  pipe-joined `surface|project|rule|wcag|target` key emitted by the a11y spec
  (project is `chromium:<viewport>:<theme>`), so a waiver must quote that exact
  string. Resolved findings (removed entries) always pass. Like `published-contract-snapshots-immutable` it
  resolves the base ref from `GITHUB_BASE_REF` / `ADR_GUARD_BASE_REF` (falling
  back to `origin/dev`/`origin/main`), fails **open** locally and **closed** under
  `ADR_GUARD_SNAPSHOT_ENFORCE`, and treats an absent base baseline as a valid
  first enrollment. The committed baseline must be a JSON array of fingerprint strings. An unparsable base baseline is unverifiable and follows the open/closed behavior above. The per-surface
  exact-set comparison against the live scan and
  the fail-closed surface reconciliation are enforced in the Playwright a11y specs
  (`frontend/e2e/a11y/`), not this check.

- `import-linter`
  Adds package-level forbidden-import contracts across the main Django app layers.

- `makemigrations --check --dry-run`
  Fails when a model or field-choices change ships without its migration. Runs in the Quality workflow. The old `missing-migrations-shifter-platform` hook is no longer configured. Adding a `TextChoices` member alters the field, so enum
  additions need a migration too. The former local migration hook addressed skipped CI tests (#680). The current hook configuration no longer contains that hook; CI owns the migration check.

- `actionlint`
  Lints GitHub Actions workflows beyond plain YAML validation.
  This includes the GCP deploy workflow's Terraform state-backend hardening
  (`_gcp-dev.yml`) so retention and IAM policy bootstrap logic remains valid.

- Django i18n/static artifact tests enforce ADR-016-R3. The owners are `tests/config/test_i18n_configuration.py` and `tests/platform/test_portal_dockerfile.py` under `shifter/shifter_platform/`. They require image builds to run `compilemessages` before `collectstatic`. They also prohibit runtime static-artifact rebuilding in `entrypoint.sh`.

- `deploy-workflow-plan-scope`
  Enforces ADR-003-R2 for the AWS deploy workflows. The `shifter_platform`
  change filter in `.github/workflows/deploy.yml` must stay scoped to
  Terraform-consumed platform files. Quality routing is separate and runs by
  exclusion: `.github/workflows/deploy.yml` must expose a `quality_relevant`
  output that runs Quality unless the diff is ordinary docs-only. That output
  also fails closed on an empty or undetermined changed-file set: `any_changed` is false when the PR-files API temporarily returns zero files. `quality_relevant` includes `any_changed != 'true'`, so an unclassifiable diff runs Quality instead of bypassing it (#2024). Guardrail
  docs, including `.github/pull_request_template.md`,
  `.github/copilot-instructions.md`, `docs/adr/**`, and this ADR enforcement
  page, are explicitly quality-relevant so ADR guard validates them. PR Gate
  must reject a skipped Quality job unless `quality_relevant` is false.
  Commit-message or label-based test skips are not accepted. Portal application
  changes must also keep
  reaching the portal image build/deploy path (#913): the check requires a `portal_image` filter covering `shifter/shifter_platform/**` and exposed by the `changes` job. The `shifter_platform` job condition must include it. The build job consumes it through `portal_image_changes`, so an application-only dispatch converges the image without Terraform. `deploy.yml` must pass literal `skip_tests: false` to `_quality.yml`. Commit-message parsing and dynamic outputs cannot select that value. Lint, architecture, and security jobs must remain independent of `inputs.skip_tests`. Other callers may skip unit tests explicitly; the deploy router never does (#760). Negative
  fixtures in `scripts/adr_guard/tests/test_adr_guard.py` include a minimal
  `_quality.yml` stub so plan-scope tests isolate one violation at a time. The check
  requires deploy concurrency to queue dispatch deploys (keyed per environment)
  rather than cancel in-flight applies; PR cancellation may remain enabled. Core, range, and platform plan and saved-plan apply commands must include `-lock-timeout=5m`. Each apply job must create and execute its local saved `tfplan`. It must not upload raw binary plans or run a fresh unplanned apply. The platform Service Discovery
  replacement check must inspect that same saved plan. Non-deploy support/test
  surfaces that are not under `shifter/**` or `mcp/**` must use the
  `quality_only` filter/output rather than being hidden in a deploy bucket:
  `scripts/stack-smoke/**` is a
  required entry so the orphaned support suites run Quality without launching
  Terraform plans, image builds, or environment deploys. Environment packs under
  `shifter/environment-packs/` are routed one pack at a time (#2550): each pack
  that `shifter/shifter_platform/Dockerfile` copies explicitly must be in
  `portal_image` and not in `quality_only`. Each other pack directory must be in
  `quality_only` and not in `portal_image`. Neither filter may route the whole
  collection. The `guardrail_docs` filter must include
  `shifter/environment-packs/**`, because pack Markdown is digest-covered
  content. On apply workflows, `_shifter-platform.yml` pushes Guacamole ECR images before the platform plan. The Guacamole module resolves image digests through `aws_ecr_image` data sources during that plan. This ordering is
  required for fresh AWS accounts where the repositories exist but the tags have
  not been published yet.

  `test_deploy_workflow.py` requires a hosted provisioner pytest gate in the Engine reusable workflow. Its image validation, build, and deployment jobs must depend on that gate. This keeps a deploy dispatch's Quality skip from bypassing
  provisioner tests on the image that is pushed and deployed. The same suite pins the engine
  `validate` image-shape job's runner placement (#1474): it uses the trusted self-hosted deploy runner class instead of `ubuntu-latest`. This prevents a hosted-runner acquisition stall from cancelling it before steps start and skipping the Platform stage. Because it is self-hosted it is
  fail-closed on `pull_request` under the `deploy-workflow-runner-exposure`
  (ADR-003-R5) invariant, keeps `contents: read` only, and carries a
  `timeout-minutes` backstop (#1220).

  `TestGcpPrivateControlPlaneAccess` keeps GCP deploy credentials on fleet
  Connect Gateway. Since #2571 the deploy command fetches them in
  `scripts/bootstrap/gcp_kube.py`. The test requires the fleet
  `memberships get-credentials` call there. It rejects the direct
  `get-gke-credentials` action and `clusters get-credentials`. The runner
  has no route to the private RFC1918 GKE control-plane endpoint. Direct
  credentials would make the workload apply time out after successful
  Terraform and image-build stages (#1850).

  `TestManualDeployDispatch` (#730) requires `workflow_dispatch` with a closed `environment` choice. Only `aws-dev` remains selectable after #2668. The environment step must use that input instead of a branch-name router. Push and pull-request events validate only, without run/apply flags.

  The optional `gcp_reconcile_foundation_image_network` dispatch input is
  forwarded only to the selected tenant's reusable GCP deploy workflow. Its
  foundation stage runs on that tenant's protected runner and Environment,
  authenticates with the existing deploy identity, and checks a saved
  `cicd-oidc` plan with `scripts/gcp/check_image_network_plan.py` before apply.
  The checker permits only the six image-network address moves and the exact
  IAP TCP port-2222 addition. Other resource or output changes fail the run;
  ordinary deployments skip the foundation stage.

  The GCP deployment-input guardrail
  (`test_gcp_workflows_keep_sensitive_tfvars_out_of_the_checkout`) requires the
  deployment inputs of `_gcp-dev.yml` in a private directory under
  `RUNNER_TEMP`, which the job removes. The CI adapter must create exclusive
  0600 files in a 0700 directory. No GitHub workflow tears down a GCP
  deployment after #2668; an operator runs `deploy.py gcp-destroy` (ADR-070).
  The destroy command renders `cloud_sql_deletion_protection = false`, which
  the shared GCP root declares (default true), so teardown lifts deletion
  protection.

  The GCE guest image guardrail
  (`test_gcp_base_image_publish_uses_gce_native_contract_and_protected_ref_gate`)
  asserts that `packer-gcp.yml` publishes the minimum base set (kali, ubuntu,
  and DC through `dc-prebaked`) as GCE-native disk tarballs to
  `ghcr.io/<owner>/<repository>/gce-<role>`. The artifact type is
  `application/vnd.shifter.gce-image.v1`, the layer media type is
  `application/vnd.shifter.gce-image.tar.gz`, and annotations record the build
  revision. The publish job checks that the validated image ID equals
  `BUILT_IMAGE_ID`, and the export object name uses `BUILT_IMAGE_ID`. The
  retired GDC qcow2 `shifter-vm-*` publish contract is gone.
  `test_gcp_guest_publication_needs_the_validation_of_the_same_run` requires publication to depend on build and validation. Validation must call the local validation workflow without secrets. No promotion workflow may exist (#2668). `gcp-deploy` and `deploy.py gcp-images` import the
  guest images of the release manifest as native GCE images after they verify
  their build provenance (`scripts/bootstrap/gcp_base_images.py`, issues #2309,
  #2571, #2679, and #2668).

- `portal-deploy-mode-source-of-truth`
  Enforces ADR-003-R4 for the AWS portal deploy path. `_shifter-platform.yml`
  must call `scripts/portal_deploy/portal_deploy.py resolve-topology` instead of reading `AWS_PORTAL_ENABLE_AUTOSCALING`. Both AWS portal roots must export `enable_autoscaling`. Single-instance deployment requires exactly one running tagged instance matching Terraform state. After ASG instance refresh, `verify-asg-image` must check every in-service instance for the new portal image tag.

- `deploy-verification-fail-loud`
  Enforces ADR-003-R3: required verification failures fail deployment.
  AWS application workloads use EKS, Kubernetes rollout/readiness checks and
  the shared Helm chart. The retained range-image path keeps its explicit
  bootstrap input and existing failure behavior. GCP verifies the selected
  environment's rendered workloads and authenticated application endpoints.
  Older ECS portal rollout checks do not describe the current application path.

- `workflow-action-sha-pinning`
  Enforces ADR-037-R1: every non-local `uses:` action in a cloud-credentialed
  workflow must pin a full 40-hex commit SHA. A workflow is classified
  credentialed when it requests `id-token: write`, runs on a self-hosted runner,
  invokes a cloud-auth action (`aws-actions/configure-aws-credentials`,
  `google-github-actions/auth`), or passes a `workload_identity_provider`. The
  check parses workflows as data via the `_dw_*` model and fails closed: an
  unparseable workflow, an unclassifiable ref, or a mutable ref (tag or branch)
  is a violation. `actions/*` is in scope. Keep the `# <version>` comment next to
  each SHA for Dependabot. Refresh guidance:
  `docs/architecture/rev1-build-deployment-provenance.md`.

- `release-workflow-provenance`
  Enforces ADR-070-R1 with ADR-004-R23, ADR-003-R5, and ADR-037-R1, R5, and R7
  on `.github/workflows/release-gcp.yml`. It reads the workflow as data and
  fails closed when the workflow is missing or cannot be parsed. Only
  `workflow_dispatch` and `workflow_call` may start the workflow (#2660). The
  only caller is the `release-gcp` job of `release-please.yml`. That workflow
  must start only on a push to `main`. The job must run only when a release tag
  points at the pushed commit, and it must not inherit secrets. That fact, the
  version, and the commit must come from an unconditional `release-commit` step
  after the Release Please action. The caller rules are in
  `scripts/adr_guard/_guard/checks/_release_workflow_caller.py`. Each job that publishes (it logs
  in to a registry, authenticates to a cloud, or pushes an image) must bind the
  `gcp-release` Environment and run on a GitHub-hosted runner. In that job, a
  step before the first publishing step must reject every ref except
  `refs/heads/main`, `refs/heads/dev`, and `refs/heads/deploy-test`. Every non-local action must pin a full commit
  SHA. Every pushed image build must produce an SBOM and maximum provenance.
  An `actions/attest-build-provenance` step in the same job must sign that
  exact digest with `push-to-registry: true`. A deployment verifies this registry
  copy of the attestation without GitHub. Before the deployer image attestation,
  an unconditional step must scan the deployer digest with the blocking Trivy
  gate (`--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`). The step must
  use `platform/deployer/gcp/trivyignore.yaml`, which holds only time-boxed
  vendor-binary exposures.

  The check also covers the guest image workflows (#2668, ADR-037-R8 and R9) in
  `scripts/adr_guard/_guard/checks/_release_workflow_guests.py`. A missing or
  unparseable guest workflow is a violation:

  - `packer-gcp.yml` starts only from `workflow_dispatch` and has no
    `environment` or `publish_target` input.
  - `packer-gcp-validate.yml` starts only from `workflow_call`. The build
    workflow calls it with a local reference. It passes only
    `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PACKER_VALIDATE_SERVICE_ACCOUNT`, and
    `GCP_PROJECT_ID`, each from the secret of the same name. A called workflow
    reads an Environment secret only when the caller passes its name.
  - Each job that publishes binds its fixed Environment (`gcp-image-build` or
    `gcp-image-validate`) and runs on a GitHub-hosted runner. Before its first
    publishing step, it rejects every ref except `refs/heads/dev` and
    `refs/heads/main`.
  - The job that pushes the guest image needs the validation job. An
    `actions/attest-build-provenance` step in that job signs the pushed digest
    with `push-to-registry: true`.

  The check runs at the `fast` and `ci` levels;
  `scripts/adr_guard/tests/test_release_workflow.py` covers it.

- `TFLint`
  Adds Terraform linting on top of `terraform fmt` and `terraform validate`.
  The initial profile is intentionally narrow: it leaves existing repo-wide
  debt rules disabled so the new gate enforces signal instead of legacy noise.

- `gitleaks`
  Scans newly introduced commits for likely secrets, with a small repo config for approved false positives.

- `cloud-factory-seam`
  Enforces ADR-005-R1: every cloud adapter module in `cloud/aws/` must have a
  counterpart in `cloud/gcp/` and vice versa. Catches provider parity drift
  when one side adds a new adapter without the other. Runs in both fast and ci
  levels.

- `kubeconform`
  Validates the rendered Helm chart for every supported values file against
  the official schemas (`k8s-schema` job). The GKE custom resources use a CRD
  catalog pinned to one commit. Catches misspelled fields, invalid resource
  types, and schema violations before they reach a cluster. Pinned to the
  target GKE Kubernetes version.

- `helm lint`
  Validates the Helm chart, the only Kubernetes renderer (ADR-007). This is the
  correct validation boundary for raw chart templates, which are not parseable
  by generic YAML tooling before render time.

- `kube-linter`
  Enforces Kubernetes security and best practices: non-root containers,
  read-only root filesystems, resource limits, privilege escalation prevention,
  and more. Configured via `.kube-linter.yaml`. The `chart-lint-security` job
  runs it on the rendered chart for every supported values file.

- `checkov-k8s`
  CIS Kubernetes benchmark and container security checks on the rendered Helm
  chart for every supported values file (`security-k8s` job, #2571). A
  **blocking gate** under ADR-004-R11 since #2558
  (`soft_fail: false`, no `continue-on-error`). This posture is separate from
  Terraform Checkov policy and from the Trivy configuration scan. Accepted-risk
  waivers use resource `checkov.io/skipN` annotations plus a matching
  `docs/adr/exceptions.yaml` entry (`rule_id: ADR-004-R11`, owner, reason with
  the Checkov policy ID, `expires_on`, `paths`).

  Making the Trivy configuration scan blocking is tracked separately in #2566;
  the [#2558 architecture preflight](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/blocking-config-security-preflight-2558.md)
  records the cross-repository contracts for that follow-up.

  ADR-008-R5's [#2564 CMEK design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/gcp-gcs-cmek-design-2564.md)
  puts every Terraform-owned GCS bucket on a customer-managed key. A
  `trivy config` scan of `platform/terraform/gcp` reports no GCP-0066 finding,
  with no exception. #2566 makes that scan a CI gate. The `terraform test` contracts of `modules/gcs-cmek`,
  `modules/portal/gcs`, `modules/image-export-storage`,
  `modules/raes-package-storage`, and `global/cicd-oidc` enforce the keys and
  the lifecycle KMS roles.

- `checkov-terraform`
  IaC security scan over first-party Terraform in `platform/terraform/`. A
  **blocking gate** under ADR-004-R11. Pre-commit (`.pre-commit-config.yaml`
  `checkov`) and the GitHub Actions `security-iac` job both consume the same
  config at `platform/terraform/.checkov.yaml`; `--soft-fail` is not set on
  either surface. Accepted-risk waivers (Checkov `skip-check` entries in
  `.checkov.yaml` or inline `# checkov:skip=CKV_X:…` comments on individual
  resources) MUST have a matching entry in `docs/adr/exceptions.yaml` with
  `rule_id: ADR-004-R11`, owner, reason (containing the Checkov policy ID),
  `expires_on`, and affected `paths`. `adr_guard.py` rejects expired
  exceptions, forcing owner re-review. Do not create a separate Checkov
  waiver registry; the ADR exceptions registry is the audit trail.

- `k8s-image-registry`
  Verifies that the image roots in the chart's GCP values files
  (`platform/charts/shifter/values-gcp-*.yaml`) point at Artifact Registry
  (`pkg.dev`), preventing accidental use of public or untrusted registries.

- `k8s-pss-labels`
  Architecture check ensuring each Namespace template in the chart carries the
  Pod Security Standards `pod-security.kubernetes.io/enforce` labels. The deploy
  commands create the platform and jobs namespaces with the same labels.
  Enforces ADR-006-R1.

- `k8s-deployment-security-context`
  Enforces ADR-006-R2 against the rendered output of
  `helm template platform/charts/shifter -f <values>` for each entry
  in `HELM_VALUES_FILES` (`values-aws-dev.yaml`, `values-aws-prod.yaml`,
  `values-gcp-dev.yaml`, `values-gcp-prod.yaml`). The chart is the only
  Kubernetes renderer (ADR-007, #2571), so the check reads exactly what a
  deploy applies. Kind-based filtering, not filename-based, means a
  Deployment rendered from any template is scanned.
  Multi-document files (`---` separator) and indentless YAML
  sequences are supported.
  Per pod template: `securityContext.seccompProfile.type` must be
  `RuntimeDefault`. Per container AND init container: the *effective*
  context (after pod-level inheritance for `runAsNonRoot`,
  `runAsUser`, `runAsGroup`) must satisfy
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` with
  no `capabilities.add`, `readOnlyRootFilesystem: true`,
  `runAsNonRoot: true`, `securityContext.privileged` not `true`, an
  optional container-level `seccompProfile.type` (when set) equal to
  `RuntimeDefault`, and `runAsUser`/`runAsGroup` set to positive
  integers (booleans are rejected since Python treats `bool` as a
  subclass of `int`). Runs in the `ci` level (`--all --level ci`,
  including CI) and in a dedicated pre-commit hook `adr-guard-k8s`
  (separate from `adr-guard-fast`) that triggers on
  `platform/charts/shifter/` changes. Not in the `fast` level, so
  unrelated `--level fast` invocations and the system-Python
  `adr-guard-fast` hook do not pull in the YAML or helm dependencies.
  **Runtime dependencies:** PyYAML (`pyyaml>=6.0`) and Helm (`v3.15.4`).
  CI's `adr-conformance` job runs on `ubuntu-latest` with uv-managed Python 3.11 and `pyyaml==6.0.2`.
  It verifies the pinned Helm archive digest before extracting it into `${RUNNER_TEMP}/helm-bin/`.
  That directory is added to `$GITHUB_PATH`.
  The test job uses the same Python and PyYAML versions under coverage.
  Chart-rendering unit tests use a Helm shim instead of the real executable.

  The local `adr-guard-k8s` hook uses `language: python` with `additional_dependencies: pyyaml>=6.0`.
  Helm remains a developer prerequisite when a changed chart selects this check.
  Complements kube-linter's `run-as-non-root`, `no-read-only-root-fs`, and `privilege-escalation-container` checks. It adds `seccompProfile`, capability drop/add, container seccomp overrides, privileged-mode, pod inheritance, and initContainer coverage. Implementation note: the validator is
  decomposed into focused helpers (`_check_container_basic_fields`,
  `_check_container_capabilities`, `_check_container_seccomp`,
  `_check_container_identity`, `_resolve_pod_spec`,
  `_resolve_pod_sc`, `_validate_containers_list`, `_chart_scan_requested`,
  `_validate_chart_renders`) so each piece
  stays under SonarCloud's cognitive-complexity threshold and tests
  can target each clause independently.

- `k8s-network-policy-coverage`
  Enforces ADR-006-R3 against the rendered Helm chart output for
  each supported values file. Every BigRAE namespace discovered in
  that output must have a default-deny `NetworkPolicy` with an
  empty pod selector and both `Ingress` and `Egress` policy types.
  The check also rejects broad egress `ipBlock` CIDRs (`0.0.0.0/0`
  and `::/0`) in BigRAE NetworkPolicies, forcing policies to use
  explicit GCLB, Google API, private service, and in-cluster service
  ranges. The one exception (#2090) is the boundary policy of a
  designated egress proxy (`content-egress`, `model-provider-egress`).
  It must select only that component, admit only named pods, and allow only TCP 443. It must exclude private, shared, loopback, link-local, multicast, and reserved IPv4 ranges through `REQUIRED_PUBLIC_EGRESS_EXCEPT`. Runs in the `ci` level and shares
  the Helm-rendered validation boundary with
  `k8s-deployment-security-context`.

- `eks-cross-stack-sourcing`
  Enforces ADR-044-R6 against the AWS EKS Terraform roots under
  `platform/terraform/environments/*/eks/`. The EKS control plane composes over existing portal and range data planes. It must get cross-stack values through native AWS data sources and SSM Parameter Store. Values include control-plane database, secrets KMS key, agent bucket, and range VPC/subnets/AMIs/instance roles. The check fails closed on
  any `terraform_remote_state` data source in those roots, which would
  couple the consumer to another stack's whole state file. Runs in both
  the `fast` and `ci` levels. The AWS/GCP provisioner-env contract
  parity that R6 also requires is proven by the platform test suite
  (`tests/shared/cloud/test_aws_runtime_role_parity.py`), not this
  structural guard.

- `no-plaintext-secrets-in-tfvars`
  Architecture check for committed `*.tfvars` under `platform/terraform/environments/` and `platform/terraform/global/`. It flags quoted string assignments to variables whose names end with a secret-bearing term: `password`, `passwords`,
  `secret`, `secrets`, `token`, `tokens`, `key`, `keys`, `credential`,
  `credentials`, `authcode`, `authcodes`, `pin_value`, or `pin_values`.
  Bare `authcode` and `pin_value` names are also blocked. Heredoc string literals
  (`name = <<EOF` / `<<-EOF`) are flagged equivalently. Object/array
  assignments to a secret-bearing variable are walked forward to the
  matching brace/bracket and flagged when any string literal appears
  inside (so `db_credentials = { password = "..." }` is caught while
  `db_credentials = { password = var.x }` is allowed). A same-line RHS scan catches function-wrapped literals such as `trimspace`, `sensitive`, and `jsonencode` calls. Multi-line wrappers use balanced `()`, `[]`, and `{}` traversal. Any inner string literal flags the assignment.
  Var/local/data references and empty strings
  are allowed. Variables ending in public-material suffixes are exempt because the material is shareable. Suffixes include `public_key`, `public_keys`, `public_cert`, `pub_key`, `pubkey`, and `authorized_keys`. A name such as `public_key_password` still has a secret suffix and remains flagged. `*.tfvars.example` files are skipped. Both `#` and `//` line comments and `/* ... */`
  block comments are stripped before matching, matching Terraform's
  HCL grammar. A file that the check cannot read or decode as UTF-8
  fails closed: the check reports it as a violation. Enforces ADR-004-R7.
  Complements gitleaks, which
  matches high-entropy random strings; this catches low-entropy
  committed credentials gitleaks ignores. Implementation note: the
  check is decomposed into focused helpers (`_collect_tfvars_candidates`,
  `_scan_tfvars_file`, `_flagged_secret_var`, `_block_assignment_has_literal`,
  `_wrapped_rhs_has_literal`, `_lines_have_string_literal`,
  `_find_balanced_close_index`, `_find_block_close_index`, `_balance_scan`,
  `_block_depth_scan`, `_scrub_line`) so each piece stays under SonarCloud's
  cognitive-complexity threshold and tests can target each clause
  independently.

- `mcp-ops-tls-strict`
  Architecture check that fails the build when any file under
  `mcp/ops/` (`.js`, `.mjs`, `.cjs`, excluding `node_modules/`)
  re-introduces `rejectUnauthorized: false` (or `0` / `null`) on a
  TLS configuration. `mcp/ops` connects to RDS PostgreSQL through an SSM forward. `mcp/ops/lib.js::buildPoolConfig` builds TLS configuration and preserves verification by setting `ssl.servername` to the captured RDS endpoint. Comments and string literals are flattened to whitespace
  before matching (mirroring `mcp-no-shell-exec`'s approach) so a
  descriptive doc-string about the prior `rejectUnauthorized: false`
  workaround does not trip the check. Backstops the `buildPoolConfig`
  unit-test invariant on every other JS file in the package. Enforces
  ADR-014-R7.

- `no-tracked-generated-artifacts`
  Architecture check that fails the build when generated or pre-staging
  sensitive artifacts are tracked in source under narrow roots. Three
  artifact families are blocked, each scoped to its own root:
  Terraform plan outputs (`tfplan`, `tfplan.binary`, `plan.out`,
  `*.tfplan`, `*.tfplan.binary`) under
  `platform/terraform/environments/` and
  `platform/terraform/gcp/environments/`; environment-pack build output
  under `shifter/environment-packs/<pack>/build/`; and license / authcode bootstrap
  material (`authcodes`, `*.authcodes`) under `temp/bootstrap/`.
  Enumeration uses `git ls-files` (tracked +
  staged + untracked-but-not-ignored) so ignored ephemeral
  workspace artifacts are intentionally allowed; a synthetic-tree
  test-mode fallback walks the filesystem. The blocked path/name
  set is centralized in `scripts/adr_guard/adr_guard.py` so adding
  another generated filename or environment root is one edit. The
  guardrail fails closed: violations name only the repo-relative
  path and a remediation hint, never echoing plan content, license
  material, or binary payloads. Backstops `.gitignore`, which does
  not retroactively un-track files that were already added (for example,
  through `git add -f`), and complements
  `no-plaintext-secrets-in-tfvars`. Enforces ADR-004-R8.

- `no-populated-secret-env-files`
  Architecture check that fails the build when a tracked
  `*-secrets.env` file under `platform/` carries a real value on
  any assignment. Comments (lines whose first non-whitespace
  character is `#`), blank lines, empty assignments (`KEY=`), and a
  small **fixed** synthetic-placeholder allowlist
  (`REPLACE_AT_DEPLOY`, `CHANGE_ME`, `PLACEHOLDER`, `EXAMPLE`, plus
  the matching bracketed forms `<replace-at-deploy>`, `<change-me>`,
  `<placeholder>`, `<example>`) are allowed; anything else is
  flagged. The bracket allowlist is an explicit fixed set rather
  than a `<...>` pattern so a committer cannot hide a real credential
  inside angle brackets (for example, `DB_PASSWORD=<attacker-known-password>`).
  The parser splits on the first `=`. Non-identifier keys such as `db.password`, `api-token`, and `export DB_PASSWORD` still receive the value check. Inline `#` does not start a comment. Only a first non-whitespace `#` marks a comment line. A non-comment, nonblank line without `=` is malformed. Containment uses `git ls-files` so gitignored local-dev
  files (for example, `platform-runtime-secrets.local.env`) are intentionally
  not scanned; a synthetic-tree test-mode fallback walks the
  filesystem for unit tests. The roots and the synthetic-placeholder
  allowlist are centralized in
  `scripts/adr_guard/_guard/checks/secret_hygiene.py`. The root is the
  whole `platform/` tree, so a secret env file in any new location is in
  scope (#2571). Failure reporting names the
  repo-relative path and the variable name only; the rejected value
  is never echoed. Real runtime secrets must flow in at deploy time
  from GCP Secret Manager, a gitignored local env file, or a
  deploy-time Kubernetes Secret. Backstops gitleaks for low-entropy
  committed credentials it ignores and prevents reintroduction of
  the failure mode resolved by PR #1207 (issue #1195). Enforces
  ADR-004-R9.

- `no-mission-control-flag-literals`
  Architecture check that fails the build when Mission Control
  runtime code carries a hardcoded CTF challenge flag. It scans the
  `shifter/shifter_platform/mission_control/` package (all runtime;
  its tests live under `shifter/shifter_platform/tests/mission_control/`,
  outside scope) and the `shifter/shifter_platform/templates/mission_control/`
  template tree (including inline `<script>` JavaScript) for
  answer-shaped `FLAG{...}` literals (case-insensitive). Detection is
  by pattern, never by a denylist of real values. Format-hint
  placeholders that describe the answer shape rather than carry one
  are intentionally **not** flagged: an empty body (`FLAG{}`), the
  ellipsis form (`FLAG{...}`), and angle-bracket templates
  (`FLAG{<16-hex>}`). The path scope deliberately excludes tests,
  docs, the native `ctf` app (where `FLAG{...}` is a documented
  format hint), and environment packs under
  `shifter/environment-packs/`, where flags are legitimate challenge
  content. Failure reporting names the repo-relative path and line
  only; the matched value is never echoed. CTF flags are low-entropy
  and are not caught by gitleaks; this is the complementary
  repo-specific backstop. Challenge answers belong to the CTF/CTFd
  content domain, not the Mission Control application path. Closes
  the #560 regression gap (the `box_info` literal-flag map removed
  during the mission_control views package split) and blocks
  reintroduction. Enforces ADR-004-R16.

- `rds-pending-modifications`
  Post-`terraform apply` gate in `_shifter-platform.yml`. Reads the portal
  Terraform outputs, then calls `aws rds describe-db-instances` for each
  `*_db_instance_id` output and fails the deploy job if any RDS instance
  still has non-empty `PendingModifiedValues` or non-`in-sync`/`applying`
  `DBParameterGroups[].ParameterApplyStatus`. Catches the failure mode
  documented in `dev/terraform.md` ("RDS Change Application") where a
  successful apply silently queues class/parameter changes for the
  maintenance window. Implementation: `scripts/check_rds_pending_modifications/`,
  with its own uv-managed dev environment, dedicated CI lint+test jobs
  (`check-rds-pending-modifications-lint` / `-tests` in `_quality.yml`),
  and the applicable Ruff commit hooks. The package test suite runs in CI. Same pattern as
  `scripts/check_layer_imports/`.

- `check-tf-kms-secrets-grant`
  Pre-commit and CI enforce the portal Secrets Manager CMK grant through `terraform-lint`. A role granting `secretsmanager:GetSecretValue` must also grant `kms:Decrypt` on that CMK. Covering wildcards include `secretsmanager:*`, `secretsmanager:Get*`, and `*`. The grant
  must satisfy all three predicates in the SAME Statement: Action
  covers `kms:Decrypt` (action wildcard matching is done with
  `fnmatch`, so `kms:*` and `kms:De*` also satisfy); Resource is
  `var.secrets_manager_kms_key_arn` or `var.secrets_kms_key_arn`
  (both module-input names refer to the same physical portal CMK in
  retained modules) or `"*"` / `["*"]` (accepted
  when the same statement carries the service condition); Condition
  `StringEquals` or `StringLike` with
  `"kms:ViaService" = "secretsmanager.<region>.amazonaws.com"`. The
  per-statement coexistence check matters because IAM evaluates each
  Statement in isolation; spreading the predicates across separate
  statements does not satisfy a single Decrypt call. Independently,
  any IAM Statement granting `kms:Decrypt` on `Resource="*"` (or
  `["*"]`) must carry a `kms:ViaService` condition pinning to some
  service; unconditioned wildcard `kms:Decrypt` is too broad.
  Existence is gated on `secretsmanager:GetSecretValue` (not file
  layout) so unrelated roles that happen to live in the same file
  are not forced to acquire unnecessary KMS grants. Scoped via the
  matching CI invocation list. Retired module paths do not establish
  current coverage. The checker and tests below define the retained rule.

  Because the role/grant pairing is evaluated **within a single
  file** (cross-file aggregation is deliberately out of scope; see
  the checker's module docstring), each role must stay in the same
  file as its `secretsmanager` and `kms:Decrypt` policies. Splitting
  them across siblings leaves the check passing while verifying
  nothing. The
  check is implemented in
  `scripts/check_tf_kms_secrets_grant/check_tf_kms_secrets_grant.py`
  and tested in
  `scripts/check_tf_kms_secrets_grant/test_check_tf_kms_secrets_grant.py`
  with stdlib `unittest` (mirrors `check_tf_iam_ec2_scope`). The checker tests run in CI. The former `check-tf-checker-tests` pre-commit hook is absent from the current configuration. Parser regressions must be checked even when current Terraform files remain valid. Enforces ADR-004-R10. This backstops the CMK-rotation failure in #52, where missing `kms:Decrypt` caused ECS secret injection to fail. The error was `AccessDeniedException: Access to KMS is not allowed`. An entrypoint `export VAR=$(fetch_runtime_secret …)` pattern had also hidden the fetch failure. See `entrypoint-lib.sh` and `tests/test_entrypoint_lib.sh` under `shifter/shifter_platform/`.

- `check-portal-target-sg-sources`
  Pre-commit and CI require narrow portal target-service ingress for Django:8000 and Guacamole client:8080. Sources must be security-group references or `module.vpc.alb_ingress_subnet_cidrs`. The whole public tier is forbidden because standalone public workloads also use it.
  Scoped to the retained `dev` and `prod` portal roots. Enforces ADR-004-R11.

- `check-tf-iam-ec2-scope`
  Pre-commit hook AND CI step rejecting mutable EC2 instance lifecycle
  actions (`TerminateInstances`, `StopInstances`, `StartInstances`,
  `ModifyInstanceAttribute`, `ModifyInstanceMetadataOptions`) on a
  wildcard resource, and requiring the BigRAE ownership resource-tag
  conditions. The original gap was missing live-Terraform CI enforcement (#1846). Local hooks and a CI unit test alone could miss a regression after bypassed hooks. The live CI invocation closed that gap. The live CI invocation was added to
  close that gap.

- `global-iam-drift-check`
  The `global-iam-drift-check` ADR guard runs at fast and CI levels through `_registry.py`. It pins `.github/workflows/iam-drift-check.yml` for the out-of-band `platform/terraform/global/iam` root. That root owns the Actions OIDC deploy role. A merged configuration edit can remain unapplied, leaving the live role behind committed configuration (#247). The check
  binds the workflow's contract on one designated plan job: a push-only trigger
  (no `pull_request`/`pull_request_target`, per ADR-003-R5), a `{dev, main}`
  branch allowlist, a `global/iam` path filter, and a real, global/iam-scoped,
  non-swallowed `terraform plan -detailed-exitcode` so a drift plan fails the
  build. The workflow runs `-refresh=false` (comparing committed config to the
  last-applied state) and is read-only, so it needs no IAM introspection the
  deploy role lacks. Enforces ADR-004-R26.

- `dev-merge-queue`
  Enforces ADR-003-R9. The check runs at fast and CI levels. It reads the `dev` ruleset in `docs/adr/dev-ruleset.json` and the workflows as data.
  The ruleset must target only `dev` and have a `merge_queue` rule that can group more than one pull request.
  `dev` must not require strict status checks, and the check accepts that only with the merge queue.
  Each required context must have a producer workflow that runs on `pull_request` to `dev` and on `merge_group`.
  A producer job condition that filters events must include `merge_group`.
  A producer is a workflow job whose `name` equals the context. Code scanning reports a context with the workflow name, so a workflow whose `name` equals the context is also a producer.

## Local Usage

During development, select the changed files and their narrowest checks first.
The full CI profile below is the required architecture-completion check, not a request to run full test suites.

Run the fast profile on the full repo:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level fast
```

Run the CI profile:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Useful ecosystem checks:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
helm lint platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml
helm template quality-check platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml > /tmp/shifter-gcp-dev.yaml
kube-linter lint --config .kube-linter.yaml /tmp/shifter-gcp-dev.yaml
kubeconform -strict -summary -kubernetes-version 1.31.0 -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/3eb90d47aba8d61919d4419dd38301536e32a94b/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' /tmp/shifter-gcp-dev.yaml
```

Run on specific files:

```bash
python3 scripts/adr_guard/adr_guard.py --files .github/workflows/_quality.yml --level fast
```

Run on staged or modified files:

```bash
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

## Docs Prose (Vale)

The [shared documentation boundary](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/documentation-tool-adoption-2804.md) describes the package, data flows, and existing security controls.
The [contributor guide](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md#documentation) gives authoring and skill-installation steps.

`tools/install-vale.sh --docs` installs doc-tools v0.1.0 and Vale 3.9.1 under ignored `.tools/` paths.
It verifies reviewed SHA-256 pins before extracting any download.
It verifies Google v0.7.1 and DocTools style archives before `vale sync` loads them.
The shared installer separately verifies ste-cli 0.10.1.
Use `make docs-tools` for the same setup that CI uses.
Automatic Vale installation supports Linux x64.

The package owns the STE wrapper, configuration, and documentation skill.
BigRAE does not copy their implementation.
The selected rules are STE-4.2, STE-5.1, and STE-6.6.
They check contractions, sentence length, and paragraph length.
The wrapper requires explicit paths and sets `--no-baseline --fail-over 0`.
Dictionary and remote analyzer features remain disabled.

`.vale.ini` retains Google errors and adds the shared DocTools style.
`Google.Contractions = NO` prevents conflicting contraction advice.
A successful check does not establish factual accuracy, Diataxis purpose, or full STE conformance.
Review those properties separately.

| Entry point | Scope and failure behavior |
| --- | --- |
| `make docs-tools` | Verified package, tool, and style setup; download or checksum errors fail |
| `make docs-changed` | Vale errors on Markdown committed since `DOCS_BASE`, which defaults to `origin/dev` |
| `make docs-required` | Vale and strict STE checks on every path in `.ste-required.txt`; empty or stale lists fail |
| `make docs-report` | CI-only report for tracked Markdown, including hidden guidance and off-site prose |
| `make docs-build` | Existing `mkdocs build --strict`; no publication |

Changed-file selection checks Git before reading NUL-delimited paths.
Deleted paths are omitted. Rename destinations, spaces, and hidden paths are retained.
A failed Git command cannot pass as an empty selection.
The changed-file target checks committed changes only.
Use the contributor guide's explicit-path commands while editing staged, unstaged, or new files.

The Vale workflow runs setup, changed-page checks, required-page checks, and the legacy corpus report.
It also exercises negative and corrected samples through the installed wrapper.
The report uses Vale `--no-exit` and STE `--fail-over -1`.
Those options report legacy findings while preserving configuration and execution errors.
The corpus log retains Vale's native summary line and the STE summary.
It does not repeat retained source excerpts.

Later rewrites add full pages to `.ste-required.txt` after both checks pass.
No baseline or second inventory is introduced.

The narrow file exclusions preserve generated root and provisioner changelogs, retained release fragments, Contributor Covenant text, and one vendored README.
`.vale.ini` records their reasons. `make docs-report` uses the same exclusions.
Preserve exact quotations and evidence with supported inline checker directives when needed.
Document the reason beside each directive.

`CONTRIBUTING.md` retains its upstream policy block verbatim under GEN-2003.
Inline directives exclude only that block; the maintained project addenda remain checked.
A whole architecture folder or all hidden files cannot be excluded as records.

Contributor guidance is reconciled under #2809.
`CONTRIBUTING.md` owns setup and explicit-path prose commands; other guidance links to it.
Local staging uses `pre-commit run`, while full suites and corpus reports remain in CI.
`.claude/skills/ship/SKILL.md` reads repository and SonarCloud identity from `.ground-control.yaml`.
The user retains feature-PR merge approval. The separately invoked release skill retains its bounded release-script exception.


Legacy Spec Kit and scenario-editor records have direct-link applicability notes and current task routes.
Their preserved bodies do not authorize current deployment, SQL mutations, or removed workflow paths.

Structured records, source docstrings, command help, and generator inputs also need reader-purpose and meaning review.
The Markdown checker does not establish coverage for those formats.
Edit maintained generator wording at its source and preserve machine-valued fields.
The delivery PR assigns those families to the later rewrite issues.

The Docs workflow builds the same existing MkDocs site through `make docs-build`.
Publication exclusions remain in `mkdocs.yml`.
Pages upload and deployment retain their existing conditions and permissions.
Prose-check coverage does not change the published set.

## How To Add A Rule

1. Add or update the ADR entry in `docs/adr/index.yaml`.
2. Implement `check_<name>(repo_root, files) -> list[Violation]` in the appropriate `_guard/checks/<family>.py` module. Add a family module only when none fits. Reuse `_guard/_common.py` and `_guard/_workflow_model.py` helpers. Register the check in `_guard/_registry.py` under `CHECKS` and the relevant `CHECK_LEVELS` profiles.
3. Decide where it belongs:
   - fast local gate
   - CI gate
   - Claude post-edit hook
   - agent policy docs
4. If the rule cannot be enforced immediately, add a dated exception to `docs/adr/exceptions.yaml`.

## Exceptions

Use exceptions sparingly. They are for temporary, explicit waivers only.

Required fields:

- `rule_id`
- `owner`
- `reason`
- `expires_on`

Optional narrowing fields:

- `checks`
- `paths`

Expired exceptions fail `adr_guard`, so they cannot linger unnoticed.

## Production-Path Quality Ownership

`.github/quality-path-filters.yaml` is the single versioned contract that maps
every production path to the blocking lint, security, and test jobs in
`.github/workflows/_quality.yml`. `scripts/quality_ownership/contract.py` is the
one parser for it. The `_quality.yml` path-detection job runs
`scripts/quality_ownership/classify_paths.py`, which validates the contract and
rejects any unclassified changed path before it emits job selection (the
fail-closed boundary). The `quality-path-ownership` check enforces ADR-004-R24 against the complete repository. It checks estate completeness, per-path lint/security/test ownership, and reachability through the real workflow.

Issue #202 assigned blocking owners to the identified gaps. ADR tooling and stack-smoke helpers have Ruff/Bandit lanes; shell harnesses also have ShellCheck. Three standalone deployment utilities share a blocking Bandit lane. MCP security rules are errors, and its shared package has a test-matrix entry. Kubernetes and Helm inputs use kube-linter.

Container inputs use BuildKit checks/ShellCheck/Trivy; the root
Docker context is separately routed through the portal build and stack smoke.
Unused root branding assets were removed after the consumer search in #2555.
A new production input needs an explicit quality owner.
The expired ADR-004-R24 exceptions were removed without renewal.

The unused CloudFormation connectors retired with their dedicated validation
and security jobs. Their quality unit, template-specific tests and live-identifier
exception retired in the same change. Maintained IaC keeps its existing gates.

To add a production path:

1. Add a quality unit to `quality_units` with its `paths` and the real
   `_quality.yml` jobs under `responsibilities.lint`,
   `responsibilities.security`, and `responsibilities.test`. Use a `{job, matrix}` entry when one job serves several packages. Set `packages` to first-party identifiers matching `scripts/check_layer_imports/layer_imports.yaml`.
2. If the path is not production source, add a typed `exclusions` entry instead
   (`docs`, `test`, `generated`, `vendor`, `metadata`, or `config`) with a
   reason. Exclusions never route jobs.
3. A responsibility without a blocking job needs a time-bounded ADR-004-R24 exception in `docs/adr/exceptions.yaml`. Its `paths` must name the `.github/quality-path-filters.yaml#<unit>:<responsibility>` anchor. There is
   no in-contract escape hatch for an owned production path.

## Repository identity (ADR-069)

`docs/adr/repository-identity.json` declares the upstream repository name,
owner, immutable repository and owner IDs, and former names. The
`repository-identity-literals` check (ADR-069-R6) reads it at the `fast` and
`ci` levels.

- The check fails on the declared or a former repository name, either ID, or
  the `ghcr.io/<owner>/` namespace in a tracked file.
- These places are allowed: the declaration, Markdown, `docs/**`, `mkdocs.yml`,
  committed Terraform `.tfvars` (deployment configuration), and the pack
  provenance records.
- In `.github/workflows/*.yml`, the only allowed form is the upstream-only
  guard comparison `github.repository_id == '<id>'` or
  `github.repository_owner_id == '<id>'`.
- The check also fails when `.ground-control.yaml` `github_repo` differs from
  the declaration.

The workflow expression model reads the same declaration for its canonical
scenario. A rename changes the declaration, `.ground-control.yaml`, and the
deployment configuration only.

The check is split for reuse: `scripts/adr_guard/_guard/_repository_identity.py`
loads and validates the declaration, and
`scripts/adr_guard/_guard/checks/repository_identity.py` runs the scan. The GCP WIF module retains a repository-name default so CKV_GCP_125 can resolve its trust subject. The identity-literals check matches owner/repository pairs and IDs, not isolated organization or repository strings. `scripts/check_tf_gcp_wif_trust` rejects a default on the
immutable IDs and on `purpose_contexts` (ADR-069-R3, ADR-070).

## Design Constraints

- Keep the default local gate fast.
- Do not rely on external dependencies for the core ADR guard.
- Prefer explicit exceptions over hidden tolerances.
- Do not make CI architecture checks skippable through the normal test-skip path.
- Keep review friction focused on guardrail files, not on ordinary feature code.

## Guardrail maintenance log

- **MCP policy contract comments (#2809)**: `.shifter.yaml` and `mcp/ops/policy.js` now describe the shipped plan/execute wrapper.
  Configuration values and JavaScript statements remain unchanged.
  The [operations security reference](https://github.com/OpenRAE/bigrae/blob/dev/mcp/ops/SECURITY.md) describes the current class-wide contract.
  The #777 preflight keeps its original body beneath a current applicability note.
- **agent-attribution matcher (`scripts/adr_guard/agent_attribution.py`)**: the
  attribution-detection regexes were simplified from `\s*.*` to `.*` to remove
  super-linear backtracking (SonarCloud `python:S8786`, ReDoS). Match behavior is
  unchanged (`.*` already spans the leading whitespace the redundant `\s*` matched)
  and is pinned by the existing `tests/test_agent_attribution.py` parity tests. No
  change to what the guardrail forbids.
- **GCP platform-core facade guard (`scripts/check_gcp_tf_modules`)**: #2535 wires
  the guard and its unit tests into the `_quality.yml` Terraform lint job. Before
  this change, no CI job or hook ran the guard, and `platform-core/main.tf` had
  three direct resources. The Secret Manager audit config now lives in
  `gcp/modules/project-audit-config`. The Cloud Build grant for the Identity
  Platform blocking function now lives in `portal/identity-platform`. Both moves
  have `moved` blocks. The guard allowlists only the cross-module
  `terraform_data.network_topology_invariant`, which creates no cloud resource.
- **GCP deploy overlay consumers (`scripts/adr_guard/tests/test_deploy_workflow.py`)**:
  #2535 adds a fourth ephemeral `bigrae.yaml` consumer to `_gcp-dev.yml`, the
  range telemetry env render. It applies `SHIFTER_CONFIG_OVERLAY_JSON` like the
  other three consumers, so the exact consumer count changes from 3 to 4. The
  invariant does not change: every consumer applies the overlay.
- **GitHub-less GCP deploy (`scripts/adr_guard/tests/test_deploy_workflow.py`)**:
  #2571 moves the GCP deploy logic from `_gcp-dev.yml` to the deploy commands
  (ADR-070). The tests now read these sources for the same invariants:

    | Invariant | Source that the tests read |
    | --- | --- |
    | HIGH and CRITICAL release scan | `gcp_release_scan.py` |
    | Running-image evidence after superseded pods finish | `gcp_rollout.py`, `gcp_deploy_stages.py` |
    | Private input files | `scripts/gcp/render_ci_deployment_inputs.py`, `gcp_terraform.py` |
    | Connect Gateway credentials | `gcp_kube.py` |
    | Operator password by variable name; Secrets through stdin | `_gcp-dev.yml`, `gcp_control_plane.py` |
    | Single range-zone input (`settings.range_cells.zones`) | `scripts/gcp/render_ci_deployment_inputs.py`, `settings_gcp_deploy.py` |

    The overlay invariant counted CI adapter runs until #2909 removed the overlay.
- **GCP running-image check (`scripts/adr_guard/tests/test_deploy_workflow.py`)**:
  #2698 adds the OpenFGA policy servers to the running-image check
  (ADR-037-R8). `gcp_rollout.py` passes a fourth `--expected-image` argument,
  `openfga=<image>`, only when the release pins a policy image. The exact
  argument count changes from 3 to 4. The test also requires the conditional
  OpenFGA argument. The invariant does not change: every workload has an
  expected image.

## Private scenario boundary

`AGENTS.md`, `.github/copilot-instructions.md`, and `.gc/plan-rules.md` require
private scenario content and adapters to remain in their owning repositories.
Public planning and review evidence uses synthetic examples; existing disclosure
does not authorize further disclosure. Review application and infrastructure
changes for identity-based scenario dispatch, embedded guest scripts, image
recipes, and accidental imports from private adapters. Pack installation cannot
authorize executable code. Runtime adapter bindings require explicit administrator
authorization against a versioned public contract.

The independently buildable SDK lives in `shifter/shifter_adapter_sdk`. Its paths
route to platform quality jobs, which run SDK lint, security analysis, contract
tests, an isolated wheel-installation test, and distribution builds. `make test`
also runs the SDK lane. Application images copy the same first-party SDK source
alongside the existing installation package; external authors consume its wheel.
SDK tests reject imports from platform applications. Tenant standup instructions
now use a base-range smoke and leave optional external pack validation and its
evidence in the owning repository.

ADR-041's tenant installation addendum permits organization administrators to
install their own plugins. Engine's organization-authority imports and config's
advisory bootstrap projection have narrow symbol allowlists. Runtime protocol
tests exercise replay, malformed output and target escalation; the worker-output
tests verify Job/Pod ownership and bounded streaming. Admission tests evaluate
the rendered CEL against actual neutral-runner manifests and privilege overrides.
API tests cover tenant denial, immutable versions, encrypted registry credentials,
retry and stale probe completion. These tests do not replace live isolation or
range-lifecycle qualification.


### External image and pack ownership (ADR-041-R10)

Private content and image recipes are maintained by their owning repositories.
Core quality jobs validate shared base-image behavior and synthetic fixtures;
private pack tests move with the implementation. Domain-controller builds require
an explicit profile and seed, with no scenario-specific default. Source removal
is preceded by a hash-verified private archive. This does not establish live
qualification of an external adapter on either cloud.

The independent adapter SDK has its own dependency update entry, like every other Python package root. Private image recipes and their dependency update targets belong to the pack owner.

### Named adapter file inputs (ADR-041-R11)

Named files reuse CMS's scoped upload ledger, quota mutex, immutable installation
and cleanup. Database constraints and custody triggers retain the file purpose,
exact object version and original range-use proof. SDK checks require the exact
declared input names, nonempty files and a 512 KiB aggregate budget; empty new
fields preserve retained request identities. CMS authorizes and fences actual
file custody before native creation and through a composition-bound material
port before worker dispatch. Engine cannot import CMS.

The rendered runtime-plugin admission policy permits only the invocation's
immutable file Secret, projected with explicit bounded keys and a fixed read-only
mount. The object-count quota allows three Secrets per reserved Job without
increasing the 16-pod execution cap. Synthetic tests evaluate rendered CEL with actual builder manifests. They reject wrong Secrets, writable or extra mounts, path traversal, unsafe modes, and oversized key sets. CMS tests cover replacement,
retention, quota cleanup, original-proof revocation and digest tampering; these
checks require no deployment or live qualification.

### Participant model credential cutover (ADR-004-R21, ADR-059)

Core no longer creates pack-specific provider roles or issues guest provider keys.
The dedicated legacy role checker moved with the removed issuer; generic IAM,
permissions-boundary and namespace checks remain enforced. The AWS
permissions boundary no longer exempts the retired role namespace from its IAM
deny. Drain existing ranges that depend on those roles using the previous release
before applying the new platform IAM. GCP teardown retains legacy credential
revocation, but new ranges receive no provider key. Guests use keyless-direct
model access (ADR-064).

### Independent SDK publication (ADR-041, ADR-042)

`adapter-sdk-release.yml` publishes BigRAE's own adapter contract package,
independently versioned from the platform. It accepts only protected `main` and a version matching source. Tests and builds use no OIDC release identity. Publication uses the exact build artifact from the `adapter-sdk-pypi` environment.

The publishing job has no checkout/build step and no token fallback.
The release boundary is covered by `test_adapter_sdk_release.py`; normal SDK
lint, security, tests and wheel builds remain in the Quality matrix. This is a
software release surface and does not publish or curate external packs.

### Tenant executable isolation (ADR-041)

Runtime plugin jobs require `runtimeClassName: gvisor` and nodes labeled
`node-restriction.kubernetes.io/shifter-pool=runtime-plugin`. The protected label
prefix prevents kubelets from attracting work by assigning themselves this label.
Both the host task profile and static/Helm admission enforce this boundary. CEL tests exercise rejection
of absent/default runtimes and platform-node placement using real rendered jobs.


The GCP node pool enables Sandbox on `COS_CONTAINERD`, with an exclusive taint
and bounded autoscaling. This follows the [GKE Sandbox deployment contract](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods).


The AWS pool uses AL2023 and a checksum-pinned gVisor point release, including its
sidecar binaries. Its MIME bootstrap installs the verified archive and configures
the runtime through [nodeadm's merge interface](https://awslabs.github.io/amazon-eks-ami/nodeadm/doc/api/).


The chart owns the EKS RuntimeClass; GKE owns its managed class. Both pools retain
one warm node and cap autoscaling at three.

An absent runtime or failed bootstrap
blocks plugin startup, with no ordinary-container fallback. Release maintenance
must follow the [gVisor installation layout](https://gvisor.dev/docs/user_guide/install/)
and [containerd configuration](https://gvisor.dev/docs/user_guide/containerd/configuration/).
The checked-in SHA-512 was verified against the complete release archive locally.

Live tests must establish actual sandbox execution and deny-all
network enforcement independently of anything the plugin reports.

### Model broker removal (ADR-068, #2909)

Issue #2909 removed the model broker and its model-access control subsystem.
These checks were removed with the components that they protected:

| Removed check | Protected component |
| --- | --- |
| `model-broker-isolation` import-linter contract | `model_broker` process |
| `_check_model_broker_scope` in `scripts/check_tf_gcp_iam_resource_scope` | Broker and invocation service accounts and roles |
| `model_source_control_read` allowance in the same checker | Tenant model-source secret reads |
| `eks-model-broker` Terraform test and broker chart tests | AWS and GCP broker packaging |
| `SHIFTER_CONFIG_OVERLAY_JSON` consumer count in `test_deploy_workflow.py` | Broker configuration overlay |

The IAM checker now rejects the former model-source secret grant like any other project-level secret grant.
The OpenAPI breaking-change gate accepts exact enum-value retirements in `openapi/v1.retirements.json`.
Each retired value is named, carries the ADR and issue, and fails the gate if the current contract reintroduces it.
The #2909 record retires the model-access paths, response fields, token scope values, and the `model_sources` integration value.

## Architecture handbook drift (ADR-022-R2)

The current-state handbook is owned through CODEOWNERS. Architecture features in
`docs/adr/documentation-coverage.yaml` declare optional `drift_sources` globs
alongside their existing user/technical pages. A mapped source change requires
review/update of that feature's technical page in the same diff; an unrelated
Markdown edit does not satisfy the rule. Record the reviewed date/revision when
the explanation stays accurate. New interfaces extend the existing manifest.

`documentation-coverage` validates all feature pages and index links on every
run. Local changed-path checks enforce pairing for their supplied scope. The always-run Quality path classifier also executes the same coverage and
drift check against the complete diff before emitting job selections, including
deleted sources. A source-only change cannot skip enforcement through the ADR
job filter; production ownership classification still excludes deleted files.

The full CI check compares the working tree and PR with the fetched base, including deleted and renamed sources. Base-revision associations remain binding when mappings change. CI's existing `ADR_GUARD_SNAPSHOT_ENFORCE=1` refuses unavailable
comparison history. Local full checks use available integration history and
fall back to working-tree changes when history is absent.

Run the existing guard and strict MkDocs build. Verify links and rendered views
because MkDocs currently reports some broken references as informational.
Automated pairing checks do not evaluate architecture prose or establish live
qualification; CODEOWNERS review supplies that judgment. Historical preflights
carry a visible status and link to the current handbook.

The documentation coverage entrypoint keeps pairing and manifest validation in
`_guard/checks/_documentation_drift.py`. The existing guard facade preserves
its public helper surface; Quality uses the same entrypoint.

The focused helper module also owns coverage-violation construction and shared
manifest shape checks. Coverage validation and CI path routing therefore retain
one set of rule identifiers and diagnostics when their implementation is split.

### Operations runbook catalog

The public operations handoff under `docs/runbooks/` retains the stable
`RB001` through `RB024` incident identifiers. `test_operations_runbooks.py` runs through existing ADR-guard unittest discovery. It checks all 24 pages, index routes, escalation boundaries, and read-only shell examples. Required sections are Symptom, Investigation, Resolution, and Prevention in that order. The same test rejects command examples that read
secret values or directly mutate Kubernetes, cloud resources, Terraform, or
Helm. This is focused GEN-001 evidence within the existing test estate, not a
new documentation schema, manifest, or adr_guard runtime check.

The deployment cleanup uses one GCP Terraform execution root, explicit selected
var-files and per-environment backend metadata. #2571 removed the Kustomize
component, and the Helm chart is now the only renderer (ADR-070). The [ADR enforcement record](../../adr/README.md)
and [recovery procedure](../../dev/deployment-configuration.md) describe retained
owners, callers and the evidence limit for undeployed environments.

Canonical GitHub routing and the workflow expression model now use
`OpenRAE/bigrae`, after the transfer to the `OpenRAE` organization (#2660).

## GitHub-less GCP deployment guardrails (ADR-070)

[ADR-070](../../adr/070-github-less-gcp-deployment.md) moves the GCP deploy
into the bootstrap CLI and removes the GitHub dependency of a deployment.
These guardrails changed with it:

- `release-workflow-provenance` (described above) guards the release
  workflow that builds the images and the deployer image.
- `scripts/check_tf_gcp_wif_trust` runs in the Terraform lint job. No `release`
  purpose exists, because the release workflow publishes to the public
  registry with the workflow token (#2659). Each token-creator or act-as grant
  outside the build self-grants must use the single `impersonation`
  resource. That resource grants each named principal access only to the
  identity of its own purpose. `impersonation_principals` must admit only `release_scan`,
  `deploy`, and `destroy`, with `user:`, `group:`, or `serviceAccount:`
  members. `github_repository_id`, `github_owner_id`, and `purpose_contexts`
  must have no default (ADR-069-R3). The resolved-plan verifier requires no WIF
  provider when no federated subject exists, and exactly one provider otherwise.
  It also requires the token-creator grants to equal the named principals.
- The Helm chart is the only Kubernetes renderer. The `k8s-lint` job is
  removed, because `chart-lint-security` runs kube-linter on the renders.
  `k8s-schema` renders the chart and runs `kubeconform -strict`, and
  `security-k8s` runs Checkov on the renders. The `validate-gcp-manifests`
  action is removed. The CKV_K8S_35 and CKV_K8S_38 exceptions now name the
  chart templates; the CKV_K8S_43 exception is removed.
- The pre-commit hook `adr-guard-gcp-overlay-identity` is now
  `adr-guard-gcp-deploy-identity`. It runs `no-live-gcp-deploy-identity` on
  the chart values files.
- The `gcp_deployer` quality unit routes `platform/deployer/**` to two jobs.
  `container-images-lint-security` runs the BuildKit check and the Trivy
  configuration scan of the deployer Dockerfile. `gcp-deployer-image` builds
  the image with a fixture release manifest and starts it.

### Adapter preparation (ADR-041-R12, ADR-063-R4)

The SDK restricts `prepare` to declared provisioning concerns, existing scalar
payload leaves and bounded responses. Core evaluates the original RAES domains,
recursive constraints and all overlapping authority before accepting any value.
Migration 0119 makes accepted preparation and its pin/parent identities immutable
through SQL. Acceptance and cancellation share the Range lock; accepted mapping
and planned invocation become visible atomically.

A destroy input retains that
mapping, or explicitly records that the mandatory pre-effect gate never opened.
The latter is a scoped proof of no effects, not an inference from a missing Job.

Core checks the complete future destroy envelope before accepting a preparation.
Prepared cleanup uses the original input; unprepared cleanup reads no mutable
image registry or guest material. Oversized encrypted snapshots are refused
before any provider effect.
Accepted preparation continues through normal provider inventory/readback.

Targeted SDK, Engine PostgreSQL, provisioner and admission-policy tests cover
confidential output, exact-value rejection, retention, tampering, replay and late
acceptance. The chart allows only one input key and an optional result key from
the same invocation Secret. See [the design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/adapter-pre-provisioning-2718.md).

### Registered GCP range projects (ADR-032-R11)

The implementation for #2716 adds Engine-owned project registration and retained
range-use records. Migration 0120 enforces immutable accepted baseline and project
identity, one unreleased use per project, immutable lease custody, and refusal to
delete an active use. A release update requires the current applied native destroy
receipt, verified absence without residuals, and matching original-lease baseline
readback. The targeted PostgreSQL tests exercise those guards through bulk SQL
writes, plus atomic multi-project allocation, organization isolation and replay.
Shared contract tests cover ciphertext identity, bounded baseline decoding and
semantic parity, including changed policy conditions and resource incarnations.

Registration uses the existing native operation input, recorded initiating proof
and append-only result inbox. Installation policy and the exact live credential
are checked before dispatch. No cloud I/O belongs in the portal or adapter worker.
These checks establish custody; they do not claim live provider realization or
deployment qualification. The [design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/registered-gcp-range-projects-2716.md)
describes the remaining provider preflight, execution and readback boundaries.
