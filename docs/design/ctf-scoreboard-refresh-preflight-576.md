# Scoreboard refresh architecture preflight (#576)

Issue #576's supplied acceptance criterion is the contract: participant and
organizer scoreboards show a new solve within 30 seconds without reloading.
This is a requirement-free maintenance run; the issue's historical CTF identifiers
do not authorize requirement-status or traceability changes. This note is design
guidance, not an implementation plan. No runtime behavior changes here.

## Decision and boundaries

Use TanStack Query's existing polling in `frontend/src/api/ctf.ts`, on both
`useCtfScoreboard` and `useCtfOrganizerScoreboard`. One scoreboard-specific
15,000 ms constant shared by those hooks leaves headroom for request/render
latency. Keep polling local to these reads; do not change global query defaults
or borrow the unrelated content-image/inbox polling constants. The constant is
the cadence seam for future tuning; no new options framework or runtime setting
is warranted. Preserve the existing event, optional bracket, and enabled inputs.

The refresh path is the existing path:

`mounted scoreboard → useQuery → apiFetch → /api/v1/ctf/events/<uuid>/… → current authorization/publication policy → scoring read → existing response → query cache → render`.

The 30 seconds is solve commit to displayed authorized result, not simply timer
frequency. Verify it with a solve immediately after an initial fetch and with
another participant doing the solving. Local submission invalidation alone
cannot meet the contract. Normal successful request/render latency must fit the
remaining budget; no browser timer guarantees freshness during a suspended tab,
offline operation, or server failure. Keep default background-tab suspension;
use hook-local focus/reconnect reconciliation as the inbox hooks do. Focus
refetch with `true` observes the global stale time; do not describe it as an
unconditional immediate request. Do not promise a hidden-tab wall-clock SLA.

Poll only while an enabled observer is mounted, retain AbortSignal propagation,
and rely on Query lifecycle cleanup. Do not stop because a returned board is
hidden, frozen, empty, or an event projection says it has ended: policy may
change, final results may be published, and that projection is not polled here.
Participant freezes intentionally withhold post-freeze solves. Organizer reads
remain live despite the displayed freeze flag.

## Existing contracts and cross-cutting gates

Paths below are relative to `shifter/shifter_platform/` unless stated otherwise.

| Layer / canonical incumbent | Obligation for this change |
| --- | --- |
| SPA state: `frontend/src/api/ctf.ts`, `queryClient.ts`; polling examples in `ctfInbox.ts`, `ctfOrganizerAlerts.ts`, `mission-control.ts` | Reuse Query scheduling, deduplication, bounded GET retry/backoff, cancellation and offline handling. Global `staleTime: 15_000` is cache freshness, not polling. Keep participant and organizer key namespaces separate, including event and bracket. Do not invalidate all CTF data every tick. |
| Transport and secret handling: `frontend/src/api/client.ts`, `csrf.ts` | Reuse `apiFetch`: same-origin session cookies, guarded API paths, URLSearchParams query encoding, request IDs and AbortSignal. No browser API token, token in URL/local storage, extra origin, custom fetch client or manual CSRF logic. These GETs create no unsafe request. |
| Participant admission: `ctf/api/views.py`, `ctf/services/event_projection.py` | Each poll rechecks public/participants-only/hidden publication. Restricted reads use `authenticated_credential`, current credential resolution, native event-read policy or exact viewing-participant authority. Preserve temporary-credential confinement and unavailable-authority failure. `AllowAny` on this API is deliberate publication policy, not unrestricted ranking access. |
| Organizer admission: `ctf/api/_base.py`, `ctf/api/organizer/_base.py`, `OrganizerScoreboardView`, `ctf/api/operation_policy.py` | Preserve session/token admission, active credential, declared read scopes, non-temporary admission and `_resolve_owned_event(..., capability=EventCapability.SUBMISSIONS)`. Native operation policy decides authority; do not replace it with owner-only, staff-flag or workspace-role checks. Never route participants through this endpoint. |
| Input shape: `ctf/api/urls.py`, `ctf/views/_parsing.py::_resolve_bracket_filter` | Keep UUID path converters and the event-owned bracket resolver. Unknown/foreign bracket values currently resolve to no selected bracket, rather than a new validation error. Preserve query parameters on every poll; introduce no duplicate parser or client-side policy validator. |
| Response shape: `ctf/api/serializers/organizer_ops.py`, `openapi/v1.json`, `frontend/src/api/schema.d.ts`, `types.ts` | Reuse `PublicScoreboardResponse` and `OrganizerScoreboardResponse` generated aliases. Hidden participant responses are successful empty projections with `scoreboard_hidden`; organizer responses deliberately lack that sentinel. No new DTO, aliases, runtime schema library or contract regeneration is needed for unchanged payloads. The current generic client casts successful JSON; it does not runtime-validate DTOs. |
| Domain/persistence: `ctf/services/scoring/_read.py`, `_maintenance.py`, `submission.py`, `award.py` | Keep server-owned ranking, tie-breaking, eligibility, dynamic scoring, team mode and bracket/freeze semantics. Live reads use materialized participant/team scores; frozen and filtered paths can require recomputation. Existing score owners maintain derived state transactionally. Polls read it; they must not trigger a rebuild command, write scores, add a table or calculate rankings in JavaScript. |
| Errors: `shared/api/errors.py`, `ctf/api/_base.py`, `frontend/src/api/errors.ts`, `queryClient.ts` | Retain controlled shared envelopes and typed `ApiError`, bounded network/5xx retry, no automatic 4xx retry, and no mutation retries. Polling is distinct from retry: a 4xx can still recur on a later interval. Do not swallow errors into empty rankings, treat denial as success, or expose proxy HTML/raw exception text. Existing page error branches must remain truthful on refresh failures. |
| Observability/privacy: `client.ts`, shared request-ID/error handling, existing scoring module loggers, `shared/log_sanitize.py` | Use existing request correlation and server diagnostics. Add no per-tick toast/audit event, response-body logging, flag/credential logging or new telemetry service. Score reads cause no business mutation requiring a new audit workflow. |
| Runtime/config/OS | Existing Vite build → Django staticfiles/WhiteNoise, same-origin DRF and database reads remain the deployment path (ADR-029). No new env binding, config shape, startup validator, scheduler, shell process, argv secret, temporary file, Redis dependency or infrastructure change. Do not cache privileged rankings in a service worker, persistent browser store or shared HTTP cache. |

## Gotchas and production evidence

- The supplied gap description is partly stale: `CtfWorkspaceLayout` now
  invalidates `ctfKeys.all` for non-message hints, including `position_changed`.
  ADR-072 makes those hints optional per event, recipient-specific, coalesced,
  and best effort; a solve need not change a rank. Retain them as an accelerator,
  never the refresh guarantee. No second socket protocol or notification kind.
- Keep stale cached organizer data out of participant queries and preserve the
  full-page session logout boundary (`frontend/src/components/app-shell.tsx`).
  This change does not introduce account switching inside a retained QueryClient.
- Poll load is roughly four requests per minute per active scoreboard observer
  (plus retries, focus and hints). Multiple tabs multiply it. Bracket views fetch
  overall and bracket rankings; frozen/filtered reads are more expensive than
  materialized live reads. Assess existing request latency and representative
  event size before claiming the 30-second bound; do not add a cache that
  ignores audience, publication changes, bracket or freeze policy.
- Reuse Vitest/Testing Library, `frontend/src/test/utils.tsx`, existing
  `ScoreboardPage.test.tsx`, `admin/MonitoringPage.test.tsx` and Query-client
  tests. Acceptance evidence must exercise both real hooks through elapsed
  time and changed server responses, with sockets absent, rather than merely
  assert an option equals a constant. Include event/bracket changes, disabled
  and unmounted queries, focus/offline recovery, error recovery, and continued
  hidden/frozen polling without disclosure. Restore fake timers/focus/online
  manager state and clear clients. A removed interval or an interval over the
  latency budget must make the freshness test fail (targeted mutation check).
- Existing backend policy evidence includes
  `tests/ctf/test_organizer_scoreboard_api.py` and
  `tests/ctf/test_drf_api_token_access.py`; preserve freeze, public/restricted
  publication, and organizer authorization contracts. No backend edits are
  expected. Run targeted frontend checks under existing package scripts; full
  suites belong in CI. Repository architecture guidance requires
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`.

## Explicit non-goals

No scoring, schema, endpoint, authentication, authorization, leaderboard storage,
notification, event lifecycle, timeline refresh, export or legacy-template
redesign. No generic polling abstraction, hand-written timers, new dependency,
global focus/poll policy, deployment service, requirement edit or implementation
in this preflight. ADR-029 and ADR-072 already cover the decisions; no new ADR or
exception is needed. Canonical repository/workflow identity remains
`.ground-control.yaml` (`OpenRAE/bigrae`); historical issue links are context, not
permission to target another repository. Do not revive historical preflight
instructions to add changelog fragments: release-please owns the changelog.
