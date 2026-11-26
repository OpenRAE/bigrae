# Participant challenge layouts: architecture preflight (#3012)

Status: pre-implementation guidance, 2026-11-23, at revision `0888c9b388b656f60e90507b58548275ae816113`.
The supplied issue #3012 is the delivery contract. No formal requirement is attached.
This explanation records boundaries and verification obligations, not implementation or release evidence.

## Decision and concept boundaries

Offer **Cards**, **List**, and **Table** in the participant challenge list. Keep cards as the default.
All three layouts present the same authorized, filtered, sorted, and grouped entries.
A list uses compact semantic list rows; a table uses semantic columns. A single-column card grid alone does not establish both layouts.

Layout and grouping are independent choices.
The existing `view=category|status|all` parameter controls grouping, including the sequence used by previous/next navigation.
Preserve that contract. Use a separate `layout=cards|list|table` parameter, with a closed parser and cards for missing or unknown values.
Reuse the existing URL update convention: omit the default, replace history, and preserve other parameters.

Keep the query string on every challenge link and the existing detail, prerequisite, sequence, and breadcrumb links.
Existing bookmarked grouping URLs must retain their meaning.

The [list design](ctf-challenge-list-views-2998.md) owns filtering, sorting, and grouping.
The [navigation design](ctf-challenge-navigation-2999.md) owns neighbors from the displayed sequence.
The earlier [list preflight](ctf-challenge-list-preflight-2998.md) excluded table layouts only from #2998's scope; #3012 supplies that scope.
ADR-013, ADR-028, ADR-029, ADR-036, ADR-040, ADR-055, and ADR-066 already cover the boundaries. No new ADR or exception is needed.

## Canonical owners and extension seam

Paths in this section are relative to `shifter/shifter_platform/frontend/`.

| Concern | Existing owner and required reuse |
| --- | --- |
| Server rows | `src/api/ctf.ts`: `useCtfChallenges` and `ctfKeys.challenges()`. Layout changes neither the request nor its cache key. |
| Wire shape | `src/api/types.ts`: generated `CtfChallengeListItem`. Do not copy it into another DTO or runtime response schema. |
| Derived entries | `src/features/ctf/challenge-list.ts`: `readListView`, `groupChallenges`, `sortChallenges`, and `isSolved`. Reuse its existing structural helper types without expanding them into wire contracts. |
| Labels | `src/features/ctf/label-filters.tsx`: `distinctLabels`, `filterByLabels`, and `LabelFilterRow`. Keep tag/topic AND semantics and choices from the full response. |
| Page state | `src/features/ctf/ChallengesPage.tsx`: `useListParams`, state branches, group sections, total, and existing card metadata. |
| Controls | `src/features/ctf/ChallengeListControls.tsx`: named fieldsets and shared toggle buttons with fixed labels and `aria-pressed`. Distinguish the layout group from the grouping control. |
| Navigation | `src/features/ctf/routes.ts` and `ChallengeDetailPage.tsx`: canonical paths, preserved search, and `adjacentChallenges`. Layout has no effect on neighbors. |
| Visual language | `src/components/ui/{button,badge,table,card,skeleton,alert}.tsx`, `src/index.css`, and `src/lib/utils.ts`. Reuse tokens, focus styles, and `cn`. |
| Existing tables | `src/features/ctf/ScoreboardPage.tsx` and `admin/ChallengesAdminPage.tsx` demonstrate the shared table primitives. Reuse primitives, not organizer actions or scoreboard row schemas. |

The extension seam is a feature-local typed layout choice applied after `readListView` produces groups.
Put its allowlisted values and parser alongside the existing presentation choices, with one owner for labels and values.
A future layout can consume the same groups without changing the API, comparators, or navigation algorithm.
Share repeated challenge metadata or links within this feature when useful; do not create a generic configurable list framework or column registry.
Keep JSX outside the pure list module. Do not import terminal-workspace persistence into CTF.

Use one active renderer, rather than mounting three copies and hiding two with CSS.
Keep the current challenge name, points, difficulty, and personal/team solve meaning available across layouts.
Use `isSolved` for completion; preserve “Solved” versus “Solved by your team.” Points are authored challenge points, not earned score.
Keep group identity separate from formatted headings, with stable challenge IDs as keys.

```text
A = participant API rows
G = readListView(A, query).groups
For each layout L:
  displayed IDs in order(L, G) = G.flatMap(group => group.items.map(item => item.id))
  each filtered ID appears exactly once
  previous/next IDs are independent of L
Header total and solved count continue to describe A, not a filtered subset
```

## Data flow and cross-cutting gates

```text
Same-origin session GET -> participant API gates -> safe projection -> existing CTF services -> database
Safe response -> TanStack Query -> readListView -> selected layout -> challenge links
Untrusted URL -> allowlisted presentation choices; no authorization or persistence command
```

Paths below are relative to `shifter/shifter_platform/` unless stated otherwise.

| Layer and canonical incumbent | How the intended design satisfies it |
| --- | --- |
| Route/account gate: `frontend/src/router.tsx`, `ctf/urls.py`, `shared/spa_host.py`, `config/middleware.py` | Retain the participant route and `CTFAccountBoundaryMiddleware`, including temporary-account and forced-password-change boundaries. No new host route, mode, permission, or `NON_API_ROUTE_POLICY` entry. |
| Authentication: `config/_drf_settings.py`, `shared/api_tokens/authentication.py`, `shared/api/principals.py`, `ctf/api/_base.py` | Keep session-cookie browser authentication and the existing bearer-first fail-closed server path. Reuse `CTF_PARTICIPANT_PERMISSIONS` and `CTF_PLAY_READ`; add no browser bearer credential. |
| Event authority: `ctf/api/participant_views.py`, `ctf/api/operation_policy.py`, participant and unified-authorization services | Keep `_resolve_active_participant`, viewing eligibility, and the existing `event.participate` operation registration. Layout carries no participant, tenant, event, scope, or capability authority. |
| Disclosure and persistence: `ctf/services/challenge/_challenge_read.py`, `ctf/models/_base.py`, `ctf/api/projections.py` | Keep service-owned event scope, soft deletion, visibility, release, and personal prerequisite checks. Reuse `participant_challenge_list` and `_team_solved_challenge_ids`; do not query organizer data or individual teammate histories. |
| Serializer and API shape: `ctf/api/serializers/participant.py`, `shared/api/{schema,contract}.py`, `openapi/v1.json`, frontend generated types | `ParticipantChallengeListItemSerializer` already supplies all needed fields. This APIView returns an array; global DRF pagination/filter settings do not automatically apply. No schema generation, new serializer, domain validation, or envelope change is needed. |
| Browser input and rendering: feature parser, React text rendering, `config/_browser_security.py` | Allowlist layout independently from grouping. Unknown values fall back without throwing. Render authored names as text; use canonical ID-based link paths. Reuse compiled handlers and Tailwind classes; no raw HTML, inline style attributes, external scripts, or CSP relaxation. |
| Transport, retries, and freshness: `frontend/src/api/{client,csrf,queryClient,ctf}.ts`, `CtfWorkspaceLayout.tsx` | Keep `apiFetch`, same-origin cookies, guarded paths, request IDs, cancellation, bounded GET retries, and existing invalidation. `invalidatePlay` and `useTeamMutation` already refresh challenges. Derive every layout from current Query data; do not persist a copied list or add polling/socket logic. |
| Errors and observability: `shared/api/errors.py`, `shared/errors.py`, `ctf/exceptions.py`, frontend `api/errors.ts`, `config/logging.py`, `shared/log_sanitize.py` | Keep safe error envelopes and request correlation. Preserve loading, failed read, no available entries, and no filter matches. Add no exception hierarchy, raw error rendering, per-click audit, response logging, or telemetry service. |
| Configuration and secrets: `config/_env_manifest.py`, `config/env-manifest.json`, repository `.shifter.yaml`, `installation.contract.BackendBundle.validate_settings`, existing deployment renderers | No new setting, environment binding, secret, or deployment input. Therefore there is no new config shape to admit or duplicate validator to write. URLs contain only presentation selections; keep credentials and private scenario facts out. |
| Host/runtime and OS exposure: `frontend/vite.config.ts`, staticfiles/WhiteNoise, existing portal image build | Ship ordinary bundled SPA assets. Add no process, subprocess argument, CLI token, upload, external destination, CDN, or server. Terraform, Helm, env bindings, and release workflows require no change. |

URL state is not private storage: direct loads reach the page host, and query strings can enter browser history, access logs, and same-origin referrers.
The layout value is a nonsensitive closed choice. Never add participant progress or credentials to it.
Browser-storage precedents exist in `frontend/src/lib/theme.ts` and mission-control's `terminalWorkspaceStorage.ts`.
They do not establish a requirement for saved CTF preferences. URL state already preserves navigation and reload behavior without a new storage boundary.

## Accessibility, reliability, and verification boundaries

Use semantic `ul`/`li` for list rows and the shared `Table` primitives for tabular data.
Give tables a group-specific accessible name or caption and proper column headers; keep actual links in cells.
Do not wrap a table row in an anchor, make rows mouse-only controls, or introduce an ARIA grid keyboard model.
Preserve visible focus, text status, keyboard operation, and stable control focus when switching layouts.

Long names, blank difficulty, empty groups, and many rows must not break the layout.
The table primitive defaults cells to `whitespace-nowrap`; choose wrapping deliberately and contain any horizontal scrolling inside the table.
Check keyboard reachability of overflow content, narrow reflow, zoom, and both existing themes.

Reuse `ChallengesPage.test.tsx`, `challenge-list.test.ts`, `ChallengeDetailPage.test.tsx`, and `src/test/utils.tsx` with synthetic API-boundary fixtures.
Verification must distinguish the three semantic layouts and establish the sequence invariant across grouping, sorting, and combined filters.
Cover invalid/missing layout, default omission, query preservation, detail/back navigation, unchanged neighbors, refetched solves, and personal/team/both/neither completion.
Layout changes must not initiate another data workflow or hide load failures as empty success.
Exercise adversarial text, long names, empty results with usable controls, and input-array immutability where transformation changes.
Use focused mutation checks on changed parsing or selection logic; no new mutation-testing framework is justified by this issue.

The existing browser scan covers only the default challenge layout.
Extend the state data in `frontend/e2e/a11y/matrix.ts` for loaded list and table states, using the same route with layout queries.
Reuse `axe.spec.ts`, its synthetic session actors, readiness assertions, desktop/narrow viewports, and exact-finding policy.
Readiness must establish that the requested layout rendered; a shared page heading alone cannot prove that.
If existing text readiness cannot distinguish layouts, the role/state assertion belongs in this same matrix and runner.

Do not add a second runner, weaken CSP, grow the accessibility baseline, or publish authenticated traces and screenshots.
Automated scans do not replace ADR-055's manual release evaluation.

Existing gates remain authoritative: frontend package scripts, ESLint accessibility rules, TypeScript, targeted Vitest/axe checks, and CI's SPA build and browser lanes.
Keep `.github/quality-path-filters.yaml`, `_quality.yml`, and `deploy.yml` as their existing owners; add no issue-specific workflow.
Architecture verification uses `python3 scripts/adr_guard/adr_guard.py --all --level ci`.
Apply the explicit-path documentation checks in `CONTRIBUTING.md` to changed prose.
Python import, Terraform, and Kubernetes checkers become relevant only if scope expands into those subsystems.

## Non-goals and anti-patterns

No backend changes, migrations, preference service, account settings, organizer redesign, new API field, export, search capability, or table-specific sorting workflow.
No column customization, pagination, virtualization, dependency, feature flag, design-system replacement, or infrastructure change is required.
Do not overload `view`, change existing comparator/category rules, sort the Query array in place, duplicate validation, or reproduce authorization in components.
Do not confuse solved with unlocked, points with awarded score, layout with grouping, or a navigation link with permission.

Keep private pack content and acceptance evidence in its owning repository; use synthetic examples here.
Implementation and publication are outside this preflight. No requirement status or traceability record needs creation for this requirement-free issue.
