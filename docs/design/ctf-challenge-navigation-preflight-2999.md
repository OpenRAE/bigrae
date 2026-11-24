# Challenge navigation: architecture preflight (#2999)

Status: pre-implementation explanation, 2026-11-23, at revision `5a2d800df09355cdbd1e6acbafe3a1a32e8e04f6`.
The supplied issue #2999 is the delivery contract. No formal requirement is attached.
This note records boundaries and verification obligations, not an implementation plan or delivery evidence.
[The navigation design](ctf-challenge-navigation-2999.md) replaces the neighbor-source decision below with browser neighbors in the list order.

## Decision and concepts

Use the existing participant detail API to supply previous and next references for the challenge's own event.
Select neighbors from `get_available_challenges(event_id, participant_id=participant.id)` in its existing `category`, `order`, `name` order.
The issue permits an order other than a challenge chain.
This choice needs no new endpoint, stored relationship, preference, or navigation framework.

The current participant list is scoped to the active event.
The detail endpoint instead resolves participation against the requested challenge's event, including readable ended or archived events.
Consequently, `useCtfChallenges` cannot supply neighbors for every valid detail page.
Do not silently redirect an earlier-event reader into their active event, or disable otherwise valid navigation to avoid this mismatch.

| Concept | Meaning and owner |
| --- | --- |
| Navigation sequence | The available challenges in the detail participant's event, ordered by the existing challenge read service. |
| Authored `order` | Display order within a category, not a globally unique position or prerequisite rank. |
| `next_challenge` | An organizer-authored, non-blocking follow-up suggestion. It is not a linear navigation chain. |
| Prerequisites | Service-owned access dependencies, not previous/next links. A team solve does not replace the viewer's prerequisite solve. |
| List presentation | Browser filters, grouping, and selectable sorts from #2998. These do not select this feature's sequence. |

`CTFChallenge.next_challenge` allows multiple incoming suggestions and cycles longer than one edge.
Its model validation and `_resolve_next_challenge` reject self-reference and cross-event references; they do not establish a linear chain.
The prerequisite graph has separate cycle checks. Do not reuse that graph or add chain validation for these buttons.

Keep navigation order explicit in the UI: category, then authored order and name.
The browser list's category presentation has additional ordering rules; it is not identical to the service's category ordering.
Do not copy those rules into Python, reinterpret category names, or promise traversal of a selected filtered list.
The existing active-name uniqueness constraint makes the service ordering unambiguous within an event.
If that constraint changes later, the owning ordering contract will need a final stable tie-breaker.

## Response and ownership boundaries

The detail projection should expose one additive, read-only `navigation` object with nullable `previous` and `next` references.
Reuse `_NamedRefSerializer` for each `{id, name}` reference.
Keep this response object distinct from the organizer's writable `next_challenge` field.
It contains no target descriptions, hints, solutions, connection information, flags, or validator configuration.
The frontend can treat an absent object as unavailable navigation during a mixed-version rollout.

The challenge service owns selection from the eligible sequence; the existing projection and serializer own its public shape.
Reuse the public `ctf.services.challenge` facade and its read policy rather than querying models from views or browser code.
An internal selection helper does not need a repository class, strategy registry, new exception hierarchy, or cross-layer contract.

Preserve the current detail admission before producing any references.
Use the requested challenge's event and the resolved participant, never a caller-supplied event or participant identity.
Carry the authenticated credential through the new read path.

Reuse `viewing_participant_for_credential` for current proof, exact event scope, credential ceilings, and live participant authority.
Require its returned participation to match the detail context, while retaining the detail's existing challenge read assertion.
An actor ID or participant row alone is not proof of current native event authority.
This feature does not add service-principal browser participation or change supported credential kinds.

```text
Authenticated detail request
  -> existing participant permissions, native credential admission, exact-event resolution
  -> assert_challenge_readable_for_participant
  -> existing event-scoped availability and ordering service
  -> participant detail projection and serializer
  -> generated API types, useCtfChallenge, React Router links
```

For one available sequence A and current index i, the navigation invariants are:

```text
IDs(A) contains only the current participant's available challenges in this event
previous = A[i - 1] when i > 0; otherwise null
next = A[i + 1] when i + 1 < length(A); otherwise null
current absent from A => both null
Every non-null reference belongs to A and differs from the current challenge
```

There is no wraparound. A single challenge has two null neighbors.
Do not fall through from a missing index of -1 to the first challenge.

Availability can change between reads; reversibility holds for the same sequence, not across organizer edits or newly satisfied prerequisites.
Use a bounded number of queries rather than loading each candidate's detail or checking each candidate through another API request.
The existing availability service already computes prerequisite exclusions for the collection.
Select only the candidate fields needed for ordering and references; avoid relation traversal per candidate.

## Cross-cutting layers to retain

Paths below are relative to `shifter/shifter_platform/` unless stated otherwise.

| Layer and canonical incumbent | How this design satisfies the boundary |
| --- | --- |
| Page hosting: `ctf/urls.py`, `shared/spa_host.py`, `frontend/src/router.tsx`, `frontend/src/features/ctf/routes.ts` | Keep the existing detail route and `ctfChallengeDetailPath`, including its trailing slash. Refreshes use the authenticated SPA host. No sidebar entry or parallel page handler is needed. |
| Temporary accounts: `config/middleware.py`, `CTFAccountBoundaryMiddleware` | Existing participant paths retain live-account and forced-password-change checks. No prefix or middleware exemption is added. |
| Authentication: `config/_drf_settings.py`, `shared/api_tokens/authentication.py`, `shared/api/principals.py` | Retain bearer-first fail-closed authentication and native credential resolution. The browser continues to use its same-origin session, not a browser bearer token. |
| Authorization: `ctf/api/_base.py`, `participant_views.py`, `ctf/services/participant/queries.py`, `challenge/_access.py` | Preserve `CTF_PARTICIPANT_PERMISSIONS`, `CTF_PLAY_READ`, exact challenge-event participant resolution, and the detail read assertion. References do not authorize a destination; every destination read passes its existing gates. |
| Native read authority: `ctf/services/principal_participation.py`, `unified_authorization.py`, `credential_scope.py`, `shared/credentials.py` | Reuse `viewing_participant_for_credential` and its current-credential, exact-event, and `event.participate` checks. Temporary credentials keep their event binding and live-account checks. Retained user, creator, or staff facts never substitute for this admission. |
| Policy inventory: `ctf/api/operation_policy.py`, `shared/authorization/*` | Keep the existing `event.participate` challenge-scoped operation. An inventory entry is not admission evidence. This feature introduces no action, credential kind, or authority migration. |
| Availability and persistence: `challenge/_challenge_read.py`, `_prerequisites.py`, `ctf/models/_base.py` | Reuse event scoping, hidden/future-release exclusion, personal prerequisite checks, and soft-delete managers. Locked challenges remain readable. No migration, stored previous pointer, read-triggered write, or bypass manager is needed. |
| Public shape: `ctf/api/projections.py`, `serializers/participant.py`, `serializers/_common.py` | Add only the navigation container and reuse the named reference. Do not expose organizer serializers, raw model dictionaries, or the suggestion graph. |
| Path and contract validation: `ctf/api/urls.py`, `shared/api/schema.py`, `shared/api/contract.py` | Retain the UUID route converter and v1 scope/error contract. Regenerate `openapi/v1.json` and `frontend/src/api/schema.d.ts`; retain drift and trusted-base compatibility checks. No new request body or JSON parser is needed. |
| Client types and transport: `frontend/src/api/types.ts`, `client.ts`, `csrf.ts`, `ctf.ts`, `queryClient.ts` | Reuse generated `CtfChallengeDetail`, `apiFetch`, `useCtfChallenge`, and `ctfKeys.challenge(id)`. Keep guarded paths, AbortSignal, request IDs, bounded GET retries, and no mutation retries. Generated TypeScript types are not a runtime response validator. Do not add a competing DTO or parsing system. |
| Rendering and accessibility: `frontend/src/components/ui/button.tsx`, `frontend/src/components/app-shell.tsx`, `config/_browser_security.py` | Use existing button styling with Router links for valid targets and actual disabled buttons for unavailable directions. Retain route-change focus handling, React text escaping, CSP, visible labels, and keyboard access. |
| Exceptions: `shared/api/errors.py`, `shared/errors.py`, `ctf/api/_base.py`, `ctf/exceptions.py`, `frontend/src/api/errors.ts` | Preserve the sanitized error envelope and typed `ApiError`. Do not serialize domain exception text or candidate names in new failure details. A failed detail read stays a failed read, not an empty successful response. |
| Observability: `config/logging.py`, `shared/log_sanitize.py`, shared request correlation | Existing request correlation and sanitized logging cover these reads. No click audit, candidate-list log, flag log, response-body log, or external telemetry service is needed. |
| Configuration and OS: `config/env-manifest.json`, repository `.shifter.yaml`, existing deployment renderers | No new environment binding, config field, secret, subprocess, CLI argument, or host port is introduced. These validators receive no new input. Keep flags and credentials out of URLs, storage, logs, and process arguments. |
| Runtime delivery: `frontend/vite.config.ts`, existing image build and staticfiles/WhiteNoise pipeline | Ship the normal static bundle through Django. No Node server, external preview, new asset host, worker, or CSP relaxation is needed. |

The list and detail admission predicates currently differ for disqualified participants.
The active-event list uses the viewing predicate; detail resolution and its read assertion use playing eligibility.
Preserve those existing contracts in this issue. Navigation must not widen detail access to match the list.

Likewise, read eligibility differs from submission, hint purchase, and file-download eligibility.
Do not gate navigation on solve state, event competition windows, or the ability to submit.
Use the existing read-admission error adapters as the pattern for native authority failures.

`CredentialUnavailable` and evaluator failures remain bounded 503 responses; explicit policy or participation denials remain denied.
`ctf_error_response` already maps domain permission failures and unavailable dependencies to the shared envelope.
Normalize native helper failures at the owning boundary; do not let `ValueError` become an unhandled 500 or a successful empty navigation object.
Preserve the endpoint's existing 403/404 behavior for challenge denials and missing challenges.
Document the new field and applicable error responses in the existing schema annotations rather than changing global exception handling.

## Browser state and freshness

Render both direction controls on a successfully loaded challenge, disabling any direction without a valid reference.
Put them in a labeled navigation region distinct from the breadcrumb.
Disabled links are unsafe: `disabled` on an anchor does not prevent activation.
Reuse `Button asChild` with `Link` only for enabled targets; do not nest interactive controls.
Use visible Previous/Next labels and escaped target names, with narrow-screen reflow and non-color disabled cues.

Changing `:id` on the same React route need not remount its content.
Already cached destination data can also bypass the loading branch that would otherwise unmount the previous form.
Challenge-scoped state must reset on identity changes: flag input, submission feedback, hint confirmation, rating state, and attachment mutation state.
Use an identity boundary keyed by challenge ID; do not reset forms whenever a background refresh updates the same challenge.
An in-flight mutation remains associated with its original challenge; its completion must not appear as the destination's result.
Do not replay it for the destination, or interpret navigation as canceling an accepted server operation.

Keep invalidation in `api/ctf.ts`, including `invalidatePlay` after submissions and hint purchases.
Those mutations can change available neighbors. Derive controls from the refreshed detail response, not a copied list in component state.
`CtfWorkspaceLayout` already invalidates CTF reads for generic live hints; do not add another socket or polling workflow.

The Query client has a 15-second stale time, disables focus refetch, and does not guarantee immediate organizer-change visibility.
Cached references are advisory. Preserve destination denials and do not retain successful content over an observed authorization failure.
Use `ApiError.status` to distinguish dependency or load failures from actual 403/404 responses.
Do not describe every failed request as a removed challenge, or add automatic mutation retries.
Do not prefetch every destination detail: it includes hint, attachment, and range-target work that neighbor selection does not need.

## Extensibility and verification obligations

The extension seam is the ordered available sequence in the owning challenge read service.
Neighbor selection should consume that sequence and the current ID; the UI should consume references without reproducing ordering or eligibility.
A future authored-chain mode needs an explicit policy for branches, cycles, missing targets, and reverse traversal at that seam.
It must reuse `_resolve_next_challenge` and model validation if suggestion writes change.
No strategy configuration or mode selector is required now.
Future pagination must select neighbors over the full eligible sequence, not one fetched page.

Reuse `tests/ctf/test_participant_api.py` and the existing challenge, release, and prerequisite service tests with synthetic database fixtures.
Verify detail-event isolation when the active event differs, readable ended/archived events, locked entries, and hidden, future, deleted, or prerequisite-gated exclusions.
Cover revoked proof, credential ceilings, exact temporary-event binding, explicit policy denial, and authority-provider failure through existing transport/provider boundaries.
Reuse native session fixtures and the configured authorization-provider test boundary in `tests/ctf/conftest.py`; do not bypass admission helpers.
Check first/middle/last/single/empty membership, category boundaries, duplicate authored order values, null references, and absence of sensitive fields.
Exercise real service behavior; ADR-019 forbids patching first-party helpers to make the desired projection appear.

Extend `frontend/src/features/ctf/ChallengeDetailPage.test.tsx` using `renderRoute` and API-boundary mocks.
Existing mocks return detail for every GET; update them to match each requested challenge and the generated response shape.
Exercise navigation, refresh/deep links, disabled controls, absent navigation, failure envelopes, cached destination transitions, and pending mutation completion.
Verify that flags, feedback, and hint confirmations cannot cross challenge identities, including Back/Forward navigation.
Use focused mutation checks for neighbor boundaries, missing membership, and event scoping once implementation tests exist.

Reuse the ADR-055 Playwright/axe stack and `frontend/e2e/a11y/matrix.ts` for loaded detail states.
The existing challenge-list matrix entry covers an empty list, not these controls.
Reuse synthetic actors and the established seed; retain CSP checks and desktop/narrow keyboard and focus checks.

Follow `docs/dev/testing.md`, `.github/quality-path-filters.yaml`, `.github/workflows/_quality.yml`, and the frontend package scripts.
Run targeted tests locally; CI owns full suites and coverage. Do not add another browser or mutation framework for this preflight.
Backend implementation must retain the ADR guard, Python lint/format, import-boundary checks, and API generation/compatibility gates.

## Non-goals

No chain editor, prerequisite change, automatic advance after solve, unsaved-input workflow, saved preference, or browser-history-based previous button.
No scoring, team attribution, release scheduling, unrelated authorization changes, active-event switch, organizer navigation, or scenario-specific behavior.
No new endpoint, database table, generic navigation abstraction, parallel serializer family, exception hierarchy, fetch client, or validation framework.
No private pack content, operational evidence, deployment, hosting, or external data transfer is part of this issue.
Existing ADR-001, ADR-013, ADR-019, ADR-028, ADR-029, ADR-040, ADR-055, and ADR-066 cover these boundaries.
No new ADR or enforcement exception is needed.
