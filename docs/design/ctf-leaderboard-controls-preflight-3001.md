# Leaderboard sorting and filtering: architecture preflight (#3001)

Status: pre-implementation guidance against revision `5a2d800df`.
Purpose: explain design boundaries, existing owners, and verification risks.
The supplied issue is the contract: participants can sort and filter leaderboards.
No formal requirement or implementation plan accompanies this note.

## Decision and scope

Apply presentation controls to the existing participant `ScoreboardPage`, shared by the default, individual, and team routes.
The public API currently returns the complete authorized ranking list without a limit or pagination.
Browser sorting and filtering can therefore cover that list without changing the API or scoring services.
Use the same controls for individual and team rows; label the name filter for the selected board.

Keep the default server order and provide a closed set of sort choices over existing displayed fields.
Name, score, and solve count are available for both row kinds.
Use explicit direction labels and numeric comparisons for numbers.
A trimmed, case-insensitive substring filter on the displayed name supplies useful filtering even when an event has no brackets.
An empty filter matches every returned row; punctuation remains literal text, never a regular expression or query language.
Exact control layout and additional sort choices remain implementation decisions within these boundaries.

Retain the existing server bracket selector and compose the name filter with its selected result.
Choose `rankings` or `bracket_rankings` first, then filter and sort a copy of that list.
Do not merge these lists or infer a team bracket result from the overall board.
Team bracket totals include only eligible members of that bracket and can change scores, solves, and ranks.
Browser name filtering changes row visibility only; it does not recalculate totals or ranks.

The separate `tools/ctf-leaderboard` display reads a generated data file through an operator-run pod query.
Its row fields and trust boundary differ from the participant API.
Do not reuse that transport, manual DOM rendering, or local pagination for this issue.
Its claim that the API cannot select individual rows in team mode is stale; the current `kind` selector already supports this.

Keep free-text filter state in component memory, following `ScenarioListPage`.
The issue does not require saved preferences or shareable filters.
Do not copy participant names into URLs, access logs, analytics, or persistent browser storage for this feature.
Challenge-list URL state is an existing option for nonsensitive enum choices, not a reason to persist free text.

## Owners and cross-cutting layers

Paths below are relative to `shifter/shifter_platform/` unless stated otherwise.

| Layer and canonical incumbent | Required reuse and security boundary |
| --- | --- |
| Presentation: `frontend/src/features/ctf/ScoreboardPage.tsx`, `format.ts` | Reuse the common page, board-kind selection, bracket control, frozen badge, and hidden/loading/error/no-event states. Reuse `rankingString`, `rankingNumber`, and `rankingKey`. Render names and filter text through React text properties. |
| Existing list patterns: `features/ctf/challenge-list.ts`, `ChallengeListControls.tsx`; `features/scenario-editor/ScenarioListPage.tsx` under `frontend/src/` | Follow closed sort choices, typed control inputs, pure transformations, copied arrays, labeled controls, and local substring filtering. Challenge-specific grouping, difficulty, and solve rules are not leaderboard helpers. No generic sort/filter engine was found in the inspected frontend. |
| UI and accessibility: `frontend/src/components/ui/{table,input,label,select,button}.tsx`, `frontend/e2e/a11y/matrix.ts` | Reuse native table semantics and existing controls. Provide keyboard access, focus visibility, labels, clear/reset behavior, and narrow-screen reflow. If headers perform sorting, use actual buttons and accurate `aria-sort` on the active header. A labeled sort selector can avoid custom header behavior. Use the existing ADR-055 accessibility runner and matrix; the matrix currently has no scoreboard surface. |
| Server state: `frontend/src/api/ctf.ts`, `queryClient.ts` | Keep `ctfKeys.scoreboard(event, bracket, kind)`, AbortSignal, `SCOREBOARD_REFRESH`, focus/reconnect behavior, and bounded retries. Name and sort controls are derived browser state; they add no network parameter or query-key dimension. Reapply them when polling returns new rows. Never mutate cached arrays or reuse organizer cache entries. |
| Transport and credentials: `frontend/src/api/client.ts`, `csrf.ts` | Keep `apiFetch`, guarded API paths, same-origin session cookies, URLSearchParams for existing server inputs, and request correlation. These GETs need no new CSRF behavior. No tokens in browser storage, URLs, process arguments, or another origin. |
| Credential confinement: `config/middleware.py`, `config/credential_scope.py`, `ctf/api/_base.py` | Preserve `CTFAccountBoundaryMiddleware`, live temporary-account confinement, forced-password-change behavior, and current-event participant permission checks. Browser controls grant no role, scope, event binding, or new route access. |
| API authentication and publication: `config/_drf_settings.py`, `shared/api_tokens/authentication.py`, `ctf/api/views.py`, `ctf/services/event_projection.py` | Preserve bearer-first fail-closed authentication and session authentication. `AllowAny` is deliberate public-publication behavior. Restricted reads use `_scoreboard_access_allowed` and `authorize_event_projection`, including current credential resolution and exact event authority. Hidden/denied projections contain empty rankings and no brackets. Never obtain extra rows through organizer APIs or another event. |
| Input parsers: `ctf/api/urls.py`, `ctf/api/serializers/organizer_ops.py`, `ctf/views/_parsing.py` | UUID routes, `PublicScoreboardQuerySerializer`, `_selected_kind`, and `_resolve_bracket_filter` remain authoritative. Preserve omitted-kind defaults, repeated/invalid-kind rejection, team-on-solo rejection, and unknown/foreign-bracket fallback. Local sort values need a closed allowlist and safe default, not another backend validator. |
| Response contracts: `PublicScoreboardResponseSerializer`, `frontend/src/api/types.ts`, `shared/api/schema.py`, `shared/api/contract.py` | Reuse `CtfScoreboard` and `CtfScoreboardKind`, sourced from `openapi/v1.json` and `frontend/src/api/schema.d.ts`. Ranking rows remain dictionary records. `JsonResponse` does not apply the response serializer at runtime; `apiFetch` casts successful JSON. Keep defensive accessors instead of adding a competing DTO or validation library. No schema generation is needed for unchanged contracts. |
| Domain and persistence: `ctf/services/scoring/{__init__,_read,_maintenance}.py`, `ctf/services/participant/queries.py` | Keep `get_scoreboard`, `get_team_scoreboard`, `ranked_participant_q`, competition ranks, last-solve tie rules, and materialized/cold read paths. The existing Django ORM and scoring services own persistence; no new repository abstraction is needed. Filtering must not write scores, rebuild materialized state, or query users/submissions per row. |
| Error envelopes: `shared/api/errors.py`, `ctf/api/_base.py`, `frontend/src/api/errors.ts` | Keep sanitized shared envelopes, typed `ApiError`, event-not-found behavior, and `scoreboard_unavailable`. No new exception hierarchy. If API validation ever changes, public field details require the owning serializer; rejected values and raw exception text must not leak. Do not convert request errors to an empty filtered result. |
| Observability: `config/middleware.py`, `shared/log_sanitize.py`, scoring module loggers | Reuse request IDs and existing diagnostics. Add no keystroke logging, row-body logging, participant-name metric labels, per-poll audit events, or telemetry service. Local display controls cause no domain mutation requiring a new audit workflow. |
| Browser and runtime: `config/_browser_security.py`, `shared/spa_host.py`, Vite and Django staticfiles/WhiteNoise | Preserve same-origin CSP, ordinary SPA hosting, and existing build packaging. No inline script, HTML injection, third-party table/search service, CSP relaxation, or persistent ranking cache. |
| Configuration and OS: `config/env-manifest.json`, `.shifter.yaml`, existing deployment bindings | This design adds no env variable, config field, secret lookup, shell command, subprocess, temporary artifact, worker, or infrastructure. Their shape validators need no amendment. No secret enters argv or a generated artifact; no host permission or credential change is required. |

The data flow stays within the existing browser-to-portal and portal-to-database boundaries:

```text
participant route -> current event -> scoreboard query(event, bracket, kind)
  -> apiFetch -> authentication/publication -> scoring service -> database
  -> existing safe projection -> Query cache -> selected ranking list
  -> local name filter -> copied sort -> common table
```

`team_mode` is an event fact; explicit `kind` determines the displayed board.
Neither is the scoring strategy, publication policy, bracket, or local sort order.
Viewing eligibility differs from ranking eligibility: a disqualified viewer can retain read access while absent from rankings.
Filtering must never reconstruct excluded participants or infer hidden scores.

## Gotchas and extensibility

- Preserve server-supplied competition ranks, including ties and gaps, after every display transformation.
  The current table falls back to `index + 1` when rank is missing.
  After sorting or filtering, that index would invent a new rank.
  Retain an original-position fallback before transformation, or show an explicit unavailable value.
- Keep the unmodified server order as the default and as the restore action.
  Alternative display sorts must not alter ranking rules or the meaning of `position_changed` notifications.
  Define equal-key ordering, using the server order or rank and stable row identity; do not rely on names being unique.
  The server does not provide an ID tie-break for every exact scoring tie, so default order need not be stable across polls.
- Use numeric comparisons for score and solves, including zero and negative award-adjusted scores.
  Specify where missing values go; do not let malformed values create `NaN` comparisons or silently coerce objects into numbers.
  `rankingNumber` currently checks the JavaScript type only; it does not establish finiteness.
  Text comparison follows the existing `localeCompare` pattern; its display ordering is not an official competition rule.
- Distinguish an empty source board from a nonempty board whose rows match no filter.
  Keep controls available so the participant can clear a filter that matches nothing.
  Hidden and failed reads must keep their existing states rather than suggesting there are no matching competitors.
- Scope control state to event and board kind; reset stale bracket selections when event context changes.
  Explicit individual/team route elements already have different React keys, but the generic route does not reset on every event change.
  Polls must preserve valid control state and focus without showing rows from the previous event, bracket, or board kind.
- The extensibility seam is a small, typed set of sort choices plus a pure projection of the selected readonly rows.
  Keep labels and allowed values together so another supported column needs one local extension, not another backend schema or framework.
  Keep control state separate from that projection so future URL support would not require changing domain logic.
  A small feature helper is reasonable; moving challenge-specific logic into `shared` is not.
- Local sorting is correct because this endpoint currently returns complete lists.
  If a future change introduces limits or pagination, revisit global filtering and ordering before shipping that change.
  Sorting one page must never claim to sort the full leaderboard.
  Existing DRF `SearchFilter`, `OrderingFilter`, and `PageNumberPagination` defaults do not automatically apply to this manual `APIView`.
  Any future server query seam belongs in its existing serializer and service boundary with ADR-040 compatibility review.
- Sorting adds browser work but no per-keystroke request or extra poll.
  Reuse derived-state memoization where useful and measure representative board sizes before proposing pagination, virtualization, or a worker.
  Frozen and team-bracket reads already cost more than live materialized reads; do not multiply them to implement display controls.

## Evidence and repository gates

Acceptance evidence must use real page controls and demonstrate changed row order and changed visible rows on both board kinds.
Use synthetic multi-row data whose names, scores, solves, ties, and official ranks differ.
Check combined bracket/name filtering, clearing, default restoration, empty matches, zero/negative scores, duplicate names, and cache immutability.
Check polling updates under active controls, event/kind changes, hidden/frozen/error states, and keyboard operation.
Test substring matching with markup-like punctuation as inert text; do not add HTML highlighting.

Reuse `frontend/src/features/ctf/{ScoreboardPage,ScoreboardRoutes}.test.tsx`, `frontend/src/api/ctfScoreboard.test.tsx`, and `frontend/src/test/utils.tsx`.
Keep tests at observable boundaries; existing examples do not authorize new first-party service mocks under ADR-019.
Use the existing Vitest/Testing Library, component axe checks, and Playwright accessibility matrix, including loaded controls and narrow viewports.
Targeted mutations that remove sorting/filtering, mutate source rows, or renumber official ranks must fail the relevant tests.
Preserve backend contracts covered by `tests/ctf/test_scoring.py`, `test_brackets.py`, `test_drf_api_token_access.py`, and `test_native_notification_authority.py`.

Use targeted local tests; complete suites remain in CI.
Frontend lint, typecheck, and build use the existing package scripts.
Architecture verification is `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Python/import changes, if justified, also require Ruff and the repository import checks.
Documentation uses explicit changed paths with the Vale and STE commands in `CONTRIBUTING.md`.

Whole-repository owners remain `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `.github/quality-path-filters.yaml`, and `.pre-commit-config.yaml`.
Keep existing API drift checks, accessibility gates, and CI coverage intact.
Use `.ground-control.yaml` for repository identity and existing workflow conventions; release-please owns changelog output.
No issue, requirement-status, traceability, or workflow edit follows from this requirement-free preflight.

## Non-goals

No scoring, rank, freeze, visibility, eligibility, notification, persistence, or event-mode changes.
No organizer-monitoring or unattended-display redesign, new endpoint, API search language, schema library, exception hierarchy, or generic table framework.
No private scenario content, external service, new dependency, deployment change, saved preference, export feature, or legacy-template revival.
ADRs 001, 013, 019, 029, 036, 040, 055, 066, and 072 already govern these boundaries.
This note applies existing rules; no new ADR, enforcement rule, or exception is needed.
It establishes design guidance only, without implementing or verifying feature behavior.
