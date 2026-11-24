# Leaderboard graphs: architecture preflight (#3004)

Status: guidance before implementation, checked against revision `5a2d800df`.
Purpose: explain design boundaries, not prescribe an implementation sequence.
The supplied issue is authoritative; no formal requirement is attached.
This note changes no runtime behavior and establishes no feature acceptance evidence.

> **Decision update.** After this preflight, the user chose score-over-time graphs and an ADR-028 amendment.
> The [design note](ctf-leaderboard-graphs-3004.md) records that decision and its API, privacy, and data-flow contract.
> Where this note recommends graphs from current scores only, without an API change, the design note governs.

## Scope and decision

The acceptance criterion requires graphs on leaderboards but specifies neither chart type nor historical data.
Use score-comparison graphs from existing ranking responses as the minimum interpretation.
Cover the default, individual, and team participant boards and the organizer monitoring scoreboard.
The organizer scoreboard and monitoring URLs already share `MonitoringPage`; they are not separate graph implementations.
Keep the existing tables for exact values and accessible alternatives.
The phrase “related pages” does not require an analytics redesign or graphs on every CTF page.

Use a small CTF presentation component shared by those scoreboard surfaces.
Its caller supplies the already-selected rows and an accessible description.
It does not fetch, authorize, rank, calculate scores, or infer the selected board from event mode.
No new API, persistence, dependency, configuration, or background workflow is needed for this design.

The existing simple bar presentation in `admin/EventAnalyticsCard.tsx` is the closest incumbent.
Reuse its Card, theme, and presentation conventions; extract a shared primitive only where both uses benefit.
Its private `Bars` helper is not a general chart contract.
Do not copy its positive-only scaling, label-based keys, or minimum visible bar height into a signed-score chart.
Native DOM or SVG geometry is sufficient; a charting framework is unnecessary for this scope.

All frontend paths below are relative to `shifter/shifter_platform/frontend/src/`.
Other platform paths are relative to `shifter/shifter_platform/`, unless identified as repository-root paths.

## Existing owners and trust boundaries

```text
participant route -> ScoreboardPage -> useCtfScoreboard(event, bracket, kind)
organizer route   -> MonitoringPage -> useCtfOrganizerScoreboard(event, bracket)
  -> apiFetch -> existing DRF authentication and publication/event policy
  -> scoring service -> database -> existing response -> isolated Query cache
  -> selected rows -> table and score-comparison graph
```

Browser-to-portal and portal-to-database remain the data trust boundaries.
Graph geometry is a presentation transformation, not a second scoring projection.

| Layer and canonical incumbent | Design obligation |
| --- | --- |
| Routes and shell: `features/ctf/routes.ts`, `router.tsx`, `app/nav.ts`; `ctf/urls.py`, `shared/spa_host.py` | Keep the current routes, navigation, authenticated shell, CSRF cookie, and uncached nonce-bearing host. No graph-specific route or navigation policy is needed. |
| Temporary accounts: `config/middleware.py`, `config/credential_scope.py`, `ctf/services/principal_participation.py` | Preserve live-participation, forced-password-change, and exact-event credential boundaries. Existing participant paths suffice; do not widen middleware admission or organizer access. |
| Authentication and scopes: `config/_drf_settings.py`, `shared/api_tokens/authentication.py`, `ctf/api/_base.py` | Retain bearer-first fail-closed authentication, session cookies, declared scopes, and existing organizer permission classes. Public `AllowAny` publication does not override an invalid credential. No new token, role, scope, or CSRF exception. |
| Publication and authority: `ctf/api/views.py`, `ctf/services/event_projection.py`, `ctf/api/organizer/scoreboard.py` | Participant graphs consume only the public projection after its publication gate. Restricted admission reuses current credential resolution and native event/participation policy. Organizer graphs use the separately authorized live projection. Hidden means no graph data; unavailable authority remains an error. |
| Input admission: UUID converters in `ctf/api/urls.py`, `PublicScoreboardQuerySerializer`, `ctf/views/_parsing.py` | Preserve closed `kind` validation, duplicate-selector rejection, solo-event team rejection, and event-owned bracket resolution. Add no graph query inputs or duplicate browser domain validation. |
| Contracts: `ctf/api/serializers/organizer_ops.py`, `shared/api/schema.py`, `shared/api/contract.py`; `api/types.ts` | Reuse `PublicScoreboardResponseSerializer`, `OrganizerScoreboardResponseSerializer`, and their generated aliases. Ranking lists are dictionary rows, not a new graph DTO. Response serializers document these paths; they do not automatically validate emitted dictionaries. |
| Transport and server state: `api/client.ts`, `api/ctf.ts`, `api/queryClient.ts` | Use `apiFetch`, same-origin cookies, encoded queries, request IDs, cancellation, and bounded retry. Derive graphs from the existing observer; do not add a second fetch or timer. Keep event/bracket/kind keys and separate organizer keys. Successful JSON is cast, not runtime schema-validated. |
| Scoring and eligibility: `ctf/services/scoring/__init__.py`, `_read.py`, `_maintenance.py`, `ctf/services/participant/queries.py` | Use existing scores, competition ranks, tie order, eligibility, and freeze/bracket semantics. `ranked_participant_q` owns ranking eligibility. Reading permission and eligibility to rank are different. No controller or browser score aggregation. |
| Persistence and lifecycle: `ctf/models/team.py`, `ctf/services/submission.py`, `ctf/services/award.py`, `ctf/services/event/_lifecycle.py` | Existing materialized columns and authoritative submission/award recomputation remain the only leaderboard storage path. Reads must not repair or write state. No chart snapshots, migration, cache table, or read-triggered reconciliation. |
| Safe rendering: `features/ctf/format.ts`, `components/ui/card.tsx`, `components/ui/table.tsx`, `index.css` | Reuse ranking accessors, stable identities, React text rendering, and theme tokens. Add finite-number guards at the geometry boundary; `rankingNumber` checks type only. These guards protect rendering, not domain admission. No HTML tooltips, injected markup, or names in executable attributes. |
| Errors and diagnostics: `shared/api/errors.py`, `ctf/api/_base.py`, `shared/errors.py`; `api/errors.ts` | Preserve sanitized error envelopes and typed `ApiError`. Do not invent chart exceptions or expose raw JSON, exception text, SQL, or proxy HTML. Preserve the page's loading, failure, hidden, empty, and no-event branches. |
| Observability and privacy: `config/middleware.py`, `config/_logging_config.py`, `config/logging.py`, `shared/audit.py`, `shared/log_sanitize.py` | Reuse request correlation, existing scoring diagnostics, ECS logging, and bounded log sanitization. No per-refresh audit workflow, ranking-body logs, names in metrics, new telemetry service, or organizer data in participant caches. |
| Browser policy: `config/_browser_security.py`, `lib/csp-nonce.ts`, `main.tsx` | ADR-036 enforces same-origin assets, no inline scripts/evaluation, denied style attributes, and nonced generated style elements. Keep graph geometry compatible with that policy. Prefer SVG geometry attributes or existing CSSOM conventions; verify actual browser behavior. Never relax CSP for a graph. |
| Build and runtime: `frontend/vite.config.ts`, platform `Dockerfile`, `shared/spa.py` | Keep image-time Vite bundling and Django staticfiles/WhiteNoise. Do not commit generated bundles, use a package CDN, add an origin/server/worker, or require runtime network access for chart assets. |
| Runtime environment: `config/_runtime_env.py`, `config/_env_manifest.py`, `config/env-manifest.json` | No environment binding is needed. Keep deployment resolution and generated binding inventory at the composition root. A graph row bound belongs in presentation code. |
| Deployment shapes: repository-root `shifter/installation/schema.py`, `shifter/installation/loader.py`, `shifter/installation/registry.py`, `platform/charts/shifter/values.schema.json` | No installation setting, backend contract, secret reference, or Helm value changes. Preserve root-model, backend-specific, and chart validation. Repository `.shifter.yaml` is the separate MCP-ops policy, not a chart configuration surface. |
| Secrets and OS exposure | This presentation-only design introduces no secret read, shell command, credential argument, server process, or worker. Do not move chart data or credentials into environment variables, process arguments, static JSON, browser storage, or external processing. |

API changes would require ADR-040 contract review and regeneration through `frontend/package.json`'s `npm run gen:api`.
Do not hand-edit `openapi/v1.json` or `api/schema.d.ts` or add a schema library for existing dictionary rows.
New operations would also need `ctf/api/operation_policy.py` and authorization-surface coverage; this design adds none.

## Semantics, reliability, and extensibility

- Participant selection uses `kind`; `team_mode` remains the event fact.
  An individual board in a team event must graph individual rows.
- Select the same overall or bracket rows once for the table and graph.
  Never replace an empty bracket result with overall results.
  Preserve current unknown/foreign bracket behavior; reset stale presentation state when event context changes.
- Participant frozen scores exclude submissions and awards at or after the cutoff.
  Organizer scores remain live even when the response reports `frozen` for display.
  Label graphs consistently with those meanings.
- Team scores deduplicate challenges by the best eligible member points and include eligible awards.
  They are not sums of individual scores. Dynamic scoring and deductions remain server-owned.
- Preserve server row order and published rank values, including ties.
  Equal scores do not necessarily mean equal ranks: the server also uses the last-solve time.
  Use participant/team IDs for identity; names can repeat or change.
  Do not treat chart position as a replacement rank or sort the shared array in place.
- Support positive, zero, and negative scores with a visible zero baseline.
  Zero must not become a positive bar; negative scores must not disappear or become absolute values.
  Handle one row, equal values, all zeros, all negatives, long names, and large scores without invalid geometry.
  Check derived scale bounds and coordinates too; valid individual numbers can still produce an invalid range or division by zero.
  Malformed values must not become credible zero scores; preserve the table and show an honest chart fallback.
- Bound plotted rows for large events while retaining the full table.
  Disclose the subset and its count; do not imply it represents every tied competitor.
  Keep the row bound as one presentation constant or component parameter, not a server limit or deployment setting.
  Bound the geometry work too; avoid spreading an unbounded leaderboard into `Math.max` or creating one element per historical sample.
  A graph row bound does not bound the existing API response or the full table.
  Do not turn it into API pagination, database limiting, or a claim of improved server capacity.
- The extension seam is a renderer input for selected rows, description, and an optional row bound.
  Participant and organizer callers retain policy, event, bracket, and board selection.
  Another comparison view can reuse rendering without changing the canonical API or adding a generic dashboard framework.
- Reuse the existing 15-second `SCOREBOARD_REFRESH` lifecycle, focus/reconnect behavior, and cancellation.
  Table and graph must update together. Do not accumulate poll samples into purported score history.
  Hide old geometry when the response becomes hidden, unavailable, or belongs to another selection.
  Do not add shared HTTP caching or persist restricted rankings beyond the existing Query lifecycle.
- Provide a meaningful graph name, score units, visible labels, and the exact-value table.
  Use instance-safe accessible-label references if the graph has SVG title or description IDs; React `useId` already serves this purpose elsewhere.
  Support narrow viewports and both themes. Do not rely on color or hover alone.
  Avoid animation on every poll and repeated live-region announcements; respect reduced-motion settings if animation is introduced.

## History and other incumbents

`ctf/services/scoring/_stats.py:get_score_timeline` and `ctf/api/organizer/scoreboard.py:ScoreTimelineView` already own participant history.
`api/ctfAdmin.ts:useCtfScoreTimeline` consumes that endpoint.
Its authorization allows native submission-management authority or the exact participant's own history.

ADR-028 separates published aggregate rankings from semi-private solve history.
Leaderboard publication does not grant access to competitors' timelines or justify new drill-down links to their solves.
The service has no freeze/bracket parameters and is not a team-history projection.
Do not fan out a timeline request per leaderboard row or sum participant histories into team history.

The service emits `timestamp`, `points`, `cumulative`, `label`, and `type`.
The current monitoring timeline table instead looks for `challenge_name` and `cumulative_score`/`total_score`.
Do not copy those mismatched keys into a graph or disguise absent values as zero.

If that related page is changed, use the actual service fields and an API-shaped fixture.
History can contain deductions, pre-start points, challenge labels, and award reasons; it is not a sanitized public series.
Historical score/rank graphs need a separately specified publication, cutoff, team, and bounded-query contract before implementation.
This issue does not require that expansion.

Repository-root `tools/ctf-leaderboard/` is a separate operator display, not the portal transport or rendering contract.
Do not import its shell refresh, pod access, environment hydration, static export, or external hosting pattern into this feature.
Its documentation about unavailable individual selection predates the implemented `kind` selector.
Likewise, Chart.js references in security prose/comments do not establish an installed frontend dependency.
The current frontend manifest has no chart library; the existing analytics bars use native elements.

## Verification and governing boundaries

Reuse `features/ctf/ScoreboardPage.test.tsx`, `ScoreboardRoutes.test.tsx`, `admin/MonitoringPage.test.tsx`, and `api/ctfScoreboard.test.tsx`.
Evidence must establish meaningful plotted values matching the selected table, not merely a graph heading or empty SVG.
Exercise individual/team/default selection, bracket isolation, signed/zero scores, duplicate names, row bounds, polling, and hidden/error transitions.
Retain keyboard access, accessible names, table equivalence, contrast, and responsive layout.

Reuse Vitest/Testing Library/axe and the existing browser CSP guard in `frontend/e2e/support/csp.ts`.
Register graph-bearing accessibility states through `frontend/e2e/a11y/matrix.ts`, using synthetic scored fixtures and a loaded-graph readiness check.
Reuse `ctf/management/commands/seed_e2e_ctf.py` and `frontend/e2e/support/actors.ts` for authenticated browser fixtures.
The current CTF seed has no scored challenges; its existing inbox state cannot prove that graph geometry rendered.

Preserve the ADR-055 exact-finding baseline; do not add another runner or hide new findings with broad exclusions.
DOM tests alone cannot establish browser CSP compatibility or visible geometry.
The current browser accessibility runner scans the dark theme; passing it alone does not establish light-theme contrast.

ADR-055 also requires release-scoped manual accessibility evidence for materially changed surfaces; automated checks do not establish WCAG conformance.
Keep browser evidence synthetic and diagnostics bounded; never publish authenticated traces, storage state, screenshots, DOM, or request/response bodies.
A targeted mutation that uses overall rows for a bracket graph or clamps deductions to zero must fail the relevant test.

Existing backend policy evidence lives in `tests/ctf/test_drf_api_token_access.py`, `test_native_notification_authority.py`, and `test_organizer_scoreboard_api.py`.
Scoring evidence lives in `test_scoring.py`, `test_brackets.py`, and `test_scoring_timeline.py`.
Keep those contracts; frontend-only changes do not require a scoring rewrite or a full local backend suite.
Run targeted tests and the existing frontend lint/typecheck/build scripts for implementation; full suites remain in CI.

Repository-root `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml` govern service boundaries.
`.github/quality-path-filters.yaml`, `.pre-commit-config.yaml`, and existing frontend/API quality jobs remain authoritative.
Architecture changes require `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Python/import changes additionally require the repository's Ruff and import checks.
No Helm, Terraform, workflow, secret, environment-schema, or deployment change is justified by this design.

ADR-001, ADR-013, ADR-028, ADR-029, ADR-036, ADR-040, ADR-055, ADR-066, and ADR-072 already govern the relevant boundaries.
No new ADR, exception, formal requirement, workflow gate, or shared domain abstraction is needed.
No new score calculation, historical ledger, authorization policy, exception hierarchy, validation framework, polling workflow, or telemetry system is in scope.
No legacy-template revival, kiosk redesign, export changes, public data hosting, or private scenario content is in scope.
Use `.ground-control.yaml`'s canonical repository for subsequent workflow operations; release-please remains the changelog owner.
