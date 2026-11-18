# Individual and team scoreboards: architecture preflight (#2968)

Status: pre-implementation guidance at revision `e31ed903a`.
Purpose: explain the boundaries for issue #2968, not prescribe an implementation sequence.
The supplied issue is the contract; this change has no formal requirement payload.

## Decision and concept boundaries

A team-mode event needs two sidebar entries that open distinct participant scoreboards.
This requires navigation and API selection changes: the current API selects team rankings whenever `CTFEvent.team_mode` is true.
The individual scoring service already supports the same event.

Keep these concepts separate:

| Concept | Existing owner | Meaning |
| --- | --- | --- |
| Event mode | `CTFEvent.team_mode` | Team participation and competition rules; remains true while viewing individual rankings. |
| Scoring strategy | `CTFEvent.scoring_mode` | Point calculation; does not select the displayed board. |
| Board selection | Participant route and optional API selector | Individual rows or team rows for the same event. |
| Publication | `scoreboard_visibility`, `is_scoreboard_frozen` | Who can read rankings and which scoring cutoff applies to both views. |
| Bracket | Event-owned participant grouping | Filters eligible participants; team totals include only that bracket's eligible members. |
| Viewer eligibility | Credential and viewing-participant policy | Determines read admission, separately from eligibility to appear in rankings. |

Reuse one participant scoreboard page, hook, public endpoint, and response envelope.
An optional closed selector, such as `kind=individual|team`, supplies the missing API seam.
Omission retains today's default: team rankings for team events and individual rankings for solo events.
Keep the response's `team_mode` as the event fact; render the selected board using the explicit selection.
Do not add a response discriminator unless the implementation demonstrates a consumer need.

Keep `/ctf/scoreboard/` working with its existing default behavior.
Give the two explicit sidebar destinations distinct pathnames through the existing CTF route builders and router.
The existing pathname can remain the default/team destination where suitable; two additional routes are not required.
This avoids changing generic scoreboard links and the shell's pathname-based active-link behavior.
Preserve participant paths under `/ctf/`, outside `/ctf/admin/`.
The Django SPA host must resolve direct loads and refreshes as well as client navigation.

Declare both entries in `frontend/src/app/nav.ts`; do not build another sidebar in the CTF layout.
The shell currently receives bootstrap, which deliberately excludes active-event summaries.
Use the existing `useCtfCurrentEvent` projection to supply minimal event presentation context to navigation filtering.
Keep event reads conditional on participant mode and reuse their Query cache.

Do not add event state to bootstrap, a global store, or a second context/provider solely for these links.
Show the team entry from the event's mode, independently of whether the viewer has an assigned team.
Hidden publication still produces the existing hidden screen; navigation does not grant ranking access.

Selection is the extensibility seam across route, page, query key, and API input.
Event and bracket remain independent inputs; another presentation can reuse these seams without changing scoring or persistence.
Event-mode visibility is presentation metadata, not a new permission policy or a general-purpose condition language.

## Existing contracts and cross-cutting layers

Paths in this table are relative to `shifter/shifter_platform/`.

| Layer and canonical incumbent | Required behavior |
| --- | --- |
| Navigation: `frontend/src/app/nav.ts`, `components/app-shell.tsx`, `app/RootLayout.tsx` | Reuse `NAV_GROUPS`, `visibleNavGroups`, advisory `ctf_participant` permission, shared links, focus management, and `aria-current`. Add only the event presentation input needed for conditional visibility. Labels distinguish the two boards. Preserve operator navigation and loading/no-event behavior. |
| Browser routing: `frontend/src/features/ctf/routes.ts`, `router.tsx`, `ctf/urls.py`, `shared/spa_host.py` | Reuse route builders and the common page. Respect trailing slashes, the SPA catch-all, login redirect, CSRF cookie, and nonce-bearing uncached shell. A new named Django route also needs classification in `ctf/api/operation_policy.py`. Existing router comments about legacy pages are partly stale; executable routing is authoritative. |
| Temporary credentials: `config/middleware.py`, `config/credential_scope.py`, `ctf/api/_base.py` | Keep `CTFAccountBoundaryMiddleware`, live-participant and forced-password-change checks. Participant browser/API prefixes already admit this surface; do not broaden them. Current-event reads retain `CTF_PARTICIPANT_PERMISSIONS`, declared play-read scope, and event-scoped participant resolution. |
| API authentication: `config/_drf_settings.py`, `shared/api_tokens/authentication.py` | Keep bearer-first fail-closed authentication followed by session authentication. `AllowAny` on `PublicScoreboardView` preserves public publication; it does not bypass authentication failures or publication policy. No new credential type, scope, role flag, or CSRF exception. |
| Publication authority: `ctf/api/views.py`, `ctf/services/event_projection.py`, `shared/api/principals.py` | Both selections use `_scoreboard_access_allowed` and `authorize_event_projection`. Restricted reads require a current credential plus native event-read policy or exact eligible participation. Preserve credential ceiling, event binding, denial, and unavailable-authority behavior. Hidden/unauthorized projections retain empty rankings, no brackets, and `scoreboard_hidden`. Do not query rankings before admission. |
| Input validation: `ctf/api/urls.py`, `ctf/views/_parsing.py`, DRF serializers | Keep UUID event routing and `_resolve_bracket_filter`. Validate the new selector with one DRF `ChoiceField` contract, also used by schema generation. Reject invalid or repeated new selector values with a bounded 400; define explicit team-on-solo selection as unavailable. Preserve omitted-selector behavior and existing unknown/foreign bracket fallback. Do not tighten all existing query inputs incidentally. |
| API publication: `ctf/api/serializers/organizer_ops.py`, `shared/api/schema.py`, `shared/api/contract.py` | Extend the existing public operation with an optional selector and truthful schema annotations. Reuse `PublicScoreboardResponseSerializer`. Generate `openapi/v1.json` and `frontend/src/api/schema.d.ts` through `npm run gen:api`; retain aliases in `types.ts`. ADR-040 drift and trusted-base compatibility checks apply. Do not hand-edit generated files or create another row schema for the existing dictionary rows. |
| Browser transport: `frontend/src/api/client.ts`, `csrf.ts` | Use `apiFetch`, guarded same-origin API paths, URLSearchParams encoding, session cookies, request IDs, and AbortSignal. GET reads require no new CSRF handling. No token in URLs, browser storage, process arguments, or another origin. |
| Server state: `frontend/src/api/ctf.ts`, `queryClient.ts` | Extend the participant key with board selection as well as event and bracket. Keep omitted/default selection distinguishable or normalize it safely. Reuse `SCOREBOARD_REFRESH`, enabled-state handling, cancellation, focus/reconnect behavior, and bounded retry policy. Fetch only the selected board; never reuse organizer cache entries. |
| Scoring and storage: `ctf/services/scoring/__init__.py`, `_read.py`, `_maintenance.py`, `ctf/services/participant/queries.py` | Call public `get_scoreboard` or `get_team_scoreboard`; pass the same freeze cutoff and resolved bracket to the selected service. Reuse `ranked_participant_q`, materialized columns, cold recomputation, competition ranks, and null-last tie-breaking. No ORM aggregation in controllers or JavaScript and no read-triggered repair/write. |
| Rendering: `frontend/src/features/ctf/ScoreboardPage.tsx`, `format.ts`, shared UI components | Reuse table, bracket selector, frozen/hidden/loading/error/empty states, `rankingKey`, `rankingNumber`, and `rankingString`. React text rendering keeps names as text. Selection controls the title and name/team column; `team_mode` alone cannot do that anymore. Do not show old-board rows under a new-board heading. |
| Errors: `shared/api/errors.py`, `ctf/api/_base.py`, `frontend/src/api/errors.ts` | Keep shared envelopes, sanitized validation details, event-not-found handling, `scoreboard_unavailable`, request correlation, and typed `ApiError`. The shared validation handler uses the view's `serializer_class` for public field names; account for that if returning field-level selector details. Never echo rejected input, raw exceptions, SQL, provider errors, or proxy HTML. |
| Observability and privacy: `config/middleware.py`, `shared/log_sanitize.py`, scoring module loggers | Reuse request IDs and existing diagnostics. No per-poll audit workflow, toast, ranking-body logging, new metric dimension containing names, or telemetry service. Publish only existing ranking fields, never raw user records, email, flags, or organizer-only data. |
| Runtime and configuration: Vite, Django staticfiles/WhiteNoise, `config/_browser_security.py`, `config/env-manifest.json` | Retain the existing image-time bundle and same-origin CSP. This feature needs no env binding, deployment config field, secret access, shell command, temporary artifact, worker, migration, infrastructure change, or new dependency. Do not introduce shared HTTP caching or persistent browser storage of restricted rankings. |

The intended data flow is:

```text
shared sidebar -> explicit participant route -> common scoreboard page
  -> Query key(event, board, bracket) -> apiFetch -> existing public DRF endpoint
  -> existing publication/credential gate -> selected scoring service -> database
  -> existing safe response -> isolated Query entry -> common table
```

Browser-to-portal and portal-to-database remain the trust boundaries.
Event scope is server-resolved; the board selector supplies no principal, tenant, permission, or scoring input.
The current `JsonResponse` path does not apply the response serializer at runtime.
Likewise, `apiFetch` casts successful JSON rather than validating its schema.
Keep runtime payloads and generated contracts aligned; reuse the existing defensive ranking accessors without adding a schema library.

## Gotchas, compatibility, and evidence

- Team totals are not necessarily the sum of individual totals.
  Existing team scoring deduplicates a challenge across members using its best awarded points, then adds eligible members' awards.
  Individual rankings use each participant's own submissions and awards.
  Do not divide, distribute, or copy team scores to individuals.
- Reading permission and ranking eligibility differ.
  Disqualified participants can retain viewing access while remaining absent from rankings.
  Hidden participants and observers do not rank; banned or unregistered participants do not gain restricted viewing access.
- Preserve cutoff comparisons, dynamic scoring, award inclusion, soft deletion, and bracket semantics by reusing scoring services.
  A frozen board reflects timestamp-filtered stored points; this issue does not introduce historical price snapshots.
  Individual live bracket reads use materialized scores; frozen reads and filtered team reads cost more.
- Reset invalid event-scoped bracket state when event context changes.
  Board changes, retries, and late responses must not mix event, bracket, board kind, or organizer results.
  Preserve the existing logout boundary, which replaces the browser document.
- The shell matches active links by pathname, not query string.
  Query-only destinations would need coordinated active-link and focus behavior; avoid that expansion here.
  Nested explicit paths can also make a generic parent link appear active simultaneously.
- `position_changed` in `ctf/services/notification/live.py` tracks team positions for team events.
  Keep that meaning and the generic scoreboard destination unchanged.
  The individual view uses the existing 15-second polling; no second notification kind or reconciliation workflow is needed.
- Ordinary API defaults and the `team_mode` response meaning are compatibility obligations under ADR-040.
  The generic ranking lists already represent either row shape.
  Reuse DRF validation without importing communication-specific `validate_query`, whose closed-query policy would change this endpoint's existing behavior.

Evidence must demonstrate two actual sidebar links opening different rankings for the same team event.
Use synthetic participants whose individual and team totals differ, including a shared challenge and an award.
Exercise routing and real hooks together; two links or two headings alone cannot establish acceptance.

Reuse `frontend/src/app/nav.test.ts`, `components/app-shell.test.tsx`, `features/ctf/ScoreboardPage.test.tsx`, and `api/ctfScoreboard.test.tsx`.
Cover selection-specific cache isolation, navigation in both directions, deep links, refresh, current-event loading, no event, and solo-event regression.
Retain polling/cancellation behavior, keyboard access, focus, accessible link names, and truthful failure states.

Backend evidence belongs beside `tests/ctf/test_drf_api_token_access.py`, `test_native_notification_authority.py`, `test_scoring.py`, and `test_spa_host.py`.
Exercise both explicit selections across public, participants-only, hidden, and frozen policy, plus wrong-event credentials, eligibility, bracket filtering, and malformed selectors.
Preserve default responses and organizer behavior; check API contract drift and compatibility.
A targeted mutation that ignores selection, omits it from the cache key, or bypasses publication must fail the relevant tests.

Use targeted local tests and the existing frontend lint/typecheck/build scripts; full suites remain in CI.
Python changes also require repository Ruff and import checks.
Architecture verification uses `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Import boundaries remain in `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml`.
Keep `.github/quality-path-filters.yaml`, existing CI coverage, and `.pre-commit-config.yaml` intact.

## Non-goals and governing boundaries

No scoring rewrite, new leaderboard storage, per-board publication settings, event-mode mutation, organizer-monitoring redesign, export changes, or notification semantics changes.
No generic scoreboard framework, navigation schema replacement, new exception hierarchy, duplicate validation library, or account/bootstrap expansion.
No legacy template revival, mobile-shell redesign, deployment change, new service, or private scenario content.
The existing sidebar is hidden below the medium breakpoint; this issue does not authorize a broader responsive-navigation redesign.

ADR-001, ADR-013, ADR-029, ADR-040, ADR-066, and ADR-072 already govern these boundaries.
No new ADR, exception, requirement-status edit, or workflow gate is needed.
The canonical repository remains `.ground-control.yaml`'s `github_repo`; release-please owns changelog updates.
This preflight changes guidance only and does not establish implemented or tested feature behavior.
