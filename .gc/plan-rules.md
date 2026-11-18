# shifter plan rules

Mandatory constraints the `/implement` skill applies during plan phase.
These encode the ADR-guard checks, guardrail-file discipline,
architectural defaults, and Kubernetes-specific validators previously in
`AGENTS.md` prose.

- Plans MUST pass `python3 scripts/adr_guard/adr_guard.py --all --level ci`
  before declaring completion.
- Plans MUST use `.ground-control.yaml`'s `github_repo` as the canonical
  GitHub repository for all `gh`, GitHub API, PR, issue, CI, Ground
  Control, and traceability operations. Extra remotes, fork history, or
  user-level skills do not override it. Target `PaloAltoNetworks/shifter`
  only when the user explicitly requests that repository in the current turn.
- Plans MUST follow ADR-069 for repository identity: runtime context for
  self-identity, `docs/adr/repository-identity.json` for upstream-only job
  guards, deployment configuration for trust anchors, and the clone's `gh`
  default repository for tooling. Do not add a repository name, ID, or
  registry owner namespace literal to code, workflows, Terraform modules, or
  tests.
- Plans MUST respect the ADR index at `docs/adr/index.yaml` and
  exceptions at `docs/adr/exceptions.yaml`. New or changed guardrails
  require matching ADR/registry updates in the same change.
- Plans that touch `.github/workflows/**` MUST pass `actionlint`.
- Plans that change the SonarCloud scan MUST keep scanner identity out of
  `sonar-project.properties`: the scan step consumes `SONAR_PROJECT_KEY` and
  `SONAR_ORGANIZATION` from non-secret repository variables, while shared
  analysis configuration stays committed. The scan attempt MUST use the upstream `github.repository_id` and `github.repository_owner_id`
  from `docs/adr/repository-identity.json` (ADR-069) as its gate.
  A non-empty variable MUST NOT be the scan gate.
  Missing or renamed variables must fail loudly upstream; forks skip deliberately. Preserve the `SONAR_TOKEN` secret boundary, PR
  `sonar.qualitygate.wait=true`, action SHA pinning, and same-delivery
  repository-variable activation/readback.
- Plans that touch Terraform under `platform/terraform/` MUST pass
  `TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"`.
- Plans that touch Python in `shifter/shifter_platform/` MUST pass
  `uv run ruff check .` and `uv run ruff format --check .` from that
  directory.
- Plans that touch Python imports MUST pass
  `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`.
- Plans that touch `platform/charts/shifter/**` MUST render the chart with
  `helm template quality-check platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml > /tmp/shifter-gcp-dev.yaml`
  and MUST pass `kube-linter lint --config .kube-linter.yaml /tmp/shifter-gcp-dev.yaml`
  and the pinned `kubeconform -strict` command in `AGENTS.md`.
- Plans MUST NOT weaken CI or local enforcement silently. Rule
  exceptions require an entry in `docs/adr/exceptions.yaml` with an
  owner and expiry.
- Plans MUST keep cross-layer access going through service boundaries;
  shared contracts live under `shared/`.
- Plans MUST NOT hand-edit `CHANGELOG.md` or add `changelog.d/` fragments.
  [release-please](https://github.com/googleapis/release-please) owns the
  product version and `CHANGELOG.md`, deriving both mechanically from the
  Conventional Commit history on `main` via its release PR (ADR-042). The eventual PR title MUST use a valid Conventional Commit type and subject.
  `pr-title-lint.yml` enforces that shape on feature PRs to `dev`.
  Release-bearing changes use `feat`, `fix`, `perf`, or a breaking marker. See `docs/DEVELOPMENT_WORKFLOW.md`.
- Plans that add a major platform feature MUST add it to `docs/adr/documentation-coverage.yaml`.
  The entry MUST include at least one user doc and one technical doc.
  The `documentation-coverage` ADR guard enforces ADR-022-R1 / GEN-001.
  It fails for missing or deprecated references, or missing links from an `index.md`.
- Changes to guardrail files (`.github/workflows/**`, `.github/CODEOWNERS`,
  `.github/pull_request_template.md`, `.github/copilot-instructions.md`,
  `.github/dependabot.yml`, `.pre-commit-config.yaml`,
  `.ground-control.yaml`, `.gc/plan-rules.md`, `.shifter.yaml`,
  `AGENTS.md`, `.importlinter`, `.tflint.hcl`, `.gitleaks.toml`,
  `.kube-linter.yaml`, `.claude/settings.json`, `.claude/hooks/**`,
  `scripts/adr_guard/**`, `release-please-config.json`, `docs/adr/**`) MUST
  stay documented in the ADR enforcement docs or registry.
## Private scenario boundary

Plans and all generated issue, PR, review, and completion metadata MUST describe
generic platform behavior using synthetic examples. They MUST NOT disclose
private pack names, repository locations, domains, topology, answers, guest
scripts, or operational evidence. Keep private evidence in its owning repository;
prior disclosure is not permission to repeat it. Core implementation MUST NOT
select behavior using scenario identity. External executable adapters MUST use
the published SDK and explicit administrator authorization, independently of pack
content installation.
