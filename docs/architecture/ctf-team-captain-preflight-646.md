# Team captain controls (#646 / CTF-503)

> **Issue-scoped preflight, 2026-11-02.** Design constraints only; no feature
> implementation or deployment evidence. The supplied issue #646 is the delivery
> contract. The [current handbook](../technical/architecture.md), ADR registry,
> and current source remain authoritative.

The change closes two gaps: captains cannot dissolve teams with recorded solves,
and organizers can reassign captaincy through the API and SPA. Existing ADR-001
service boundaries, ADR-019 boundary testing, ADR-052 audit discipline, and
[ADR-066](../adr/066-account-principal-resource-scope.md) authorization suffice.
No new ADR, role system, repository layer, workflow engine, or configuration is
needed. Paths below are relative to `shifter/shifter_platform/` unless stated.

Data flow: untrusted browser/API IDs → authenticated DRF boundary → persisted
team/event resolution and exact policy decision → team service with locked
invariants → database mutation and existing audit/invalidation → minimal response.
Database truth owns membership and captaincy; no browser claim crosses that
boundary as authority. No new process or external data flow is introduced.

## Domain decisions and boundaries

`ctf.services.team` owns both rules. Keep participant authorization and organizer
authorization separate entry points, sharing the small captain-assignment write
and its membership invariant. Organizer reassignment takes an explicit team,
target participant, and actor credential/admission; it must not impersonate the
old captain, require that captain to remain compete-eligible, or expose a
`skip_captain_check`/`force` switch. Reuse `assert_event_action` and the existing
`event.manage_teams` action for direct service callers as well as API admission.
The explicit actor and team are the extension seam for another trusted caller;
authority never comes from request booleans or a participant identity.

The target must resolve through the live participant manager to a member of the
live target team in the same event. Reassignment changes only `captain`, using
the normal save path; it neither joins a participant nor changes their identity,
participation role, standing, scores, customer membership, or event authority.
Allow recovery from null/stale captain references. Do not invent a restriction
to ranked players or active competitors: the requirement says member, and the
existing transfer accepts a live teammate. Reassigning the existing captain can
be a successful no-op. Captaincy is a team management fact, not an OpenFGA role,
event staff assignment, cohort, workspace, or customer account membership.

The executable predicates to preserve in service tests are:

```text
assignable(T, P) = live(T) AND live(P) AND P.team_id = T.id
                  AND P.event_id = T.event_id
has_solves(T) = exists live CTFSubmission S:
               S.is_correct AND S.participant.team_id = T.id
               AND S.participant.event_id = T.event_id
captain_dissolution(T, actor) requires current captain authority AND NOT has_solves(T)
organizer_assignment(T, P, actor) requires event.manage_teams(T.event) AND assignable(T, P)
```

Use correct submissions, including zero-point solves, independently of participant
ranking eligibility. Incorrect attempts and awards are not solves. Do not use
`total_score`, `cached_score`, `cached_solve_count`, hidden status, or
`ranked_participant_q` as the denial predicate: caches and rankings intentionally
exclude contributions that still exist. An ORM relationship join does not apply
the related participant's default manager; be deliberate about that distinction
rather than silently removing recorded solves of soft-deleted members.

**Attribution limit:** submissions store a participant, not a team-at-solve-time
reference. Existing team scoring follows current membership. The predicate above
uses that same attribution and active submission records; explicitly soft-deleted
submissions are no longer active solves. A departed member's history cannot prove
that this team ever solved a challenge. Do not claim an immutable historical ban
or add a historical team ledger as an incidental fix. If “recorded” is intended
to include removed submissions or former members' solves, that needs an explicit
contract decision before coding that interpretation; the present schema cannot
reconstruct historical team ownership reliably.

`leave_team` deletes a lone captain's team too. The same dissolution precondition
must cover that branch before clearing membership. Ordinary member leave and
captain transfer retain their existing behavior. Do not put this restriction in
`CTFTeam.delete()` or generic model validation: organizer event teardown and
maintenance are different operations. Reuse one service precondition at the
participant dissolution boundaries, preserving `disband_team`'s existing bulk
membership invalidation and soft deletion. Denial must change nothing.

## Cross-cutting layers to reuse

| Layer | Canonical incumbent and required behavior |
| --- | --- |
| Authentication and browser boundary | `config/_drf_settings.py`, `shared.api_tokens.authentication`, `shared.api.permissions`, and `frontend/src/api/client.ts`: retain fail-closed credential resolution, bearer authentication, session CSRF, same-origin transport, and request correlation. No CSRF exemption or credential in URLs. |
| Endpoint scopes and resource policy | `ctf.api._base.CTF_ORGANIZER_PERMISSIONS`, organizer `_EVENT_WRITE`, `_resolve_owned_event(..., capability="teams")` or its explicit action option, `_credential`, and `ctf.services.authorization.assert_event_action`: derive the event from the persisted team and require `event.manage_teams`. Transport scope alone grants nothing. Preserve exact credential ceilings, event ancestry and unavailable-versus-denied behavior in `unified_authorization.require_event_action`. Do not copy legacy owner/staff/superuser checks. |
| Policy vocabulary and coverage | `ctf.services.event._staff_policy`, `shared.authorization`, and `ctf.api.operation_policy.API_OPERATION_POLICY` already define the action/capability model. Register every new operation, including any organizer read projection, under its actual action and persisted resource locator; `tests/ctf/test_authorization_operation_map.py` requires exact coverage of published operations. A moderator's `participants` capability is insufficient for team administration. |
| Parsing and wire shapes | DRF parsers, `TeamMemberRequestSerializer` (`participant_id` UUID), `extend_schema`, and `ctf.api.serializers` are the canonical transport definitions. Reuse the UUID body; validate team membership in the service, not a second serializer validator. URL UUID converters validate path shape. Author only the minimal organizer response/read projection needed; never serialize an ORM model wholesale. |
| Contract generation and SPA | `manage.py api_contract`, `openapi/v1.json`, frontend `npm run gen:api`, generated `src/api/schema.d.ts`, and `src/api/types.ts` own schema generation and aliases. Reuse `ctfAdmin.ts`/`ctfAdminOps.ts`, `apiFetch`, `ctfKeys`, TanStack mutations, `describeMutationError`, and existing form/button/confirmation components. Do not hand-edit generated types or add parallel fetch/error/state frameworks. |
| UI admission and disclosure | Organizer participant pages are precedents for mutation UX, not authority for a teams action. Their participant payloads expose `team_name`, not a reliable team identifier or member roster. Supply only the needed stable IDs/display names/captain state through an authorized projection; do not load the unrestricted participant directory merely to build a team picker. Respect pagination and scope any selection to the target team. Hide/disable controls according to the existing capability pattern, with server policy authoritative. |
| Join secret | `ctf.api.projections.participant_team` and `ParticipantTeamSerializer` deliberately disclose `invite_code` only to the actual captain. Do not reuse this actor-relative response by pretending an organizer is that captain. Organizer reassignment needs no invite code, email, principal credential, or submitted flag. Preserve old/new captain redaction after refresh. |
| Persistence and model validation | `CTFBaseModel.save/full_clean`, `SoftDeleteManager`, `CTFParticipant.clean`, `CTFSubmission.clean`, `transaction.atomic`, and row locks remain canonical. Participant validation covers same-event/team-mode membership, but `CTFTeam.captain` is only a nullable FK: it does not enforce captain membership. Service checks are essential. Do not add a migration or global non-null constraint that breaks team creation or recovery. |
| Effects and access invalidation | `ctf.signals`, `ctf.bridges.cms_invalidate_model_access_authority`, typed `shared.model_access.AuthorityInvalidation`, and disband's bounded 62-member invalidation batches already cover membership/deletion changes. Bulk updates bypass save signals, so preserve explicit invalidation. Captain-only changes do not change membership authority; do not create new policy tuples, invalidation jobs, or scoreboard work for them. |
| Exceptions and envelopes | Reuse `CTFStateError` for solved-team refusal, `CTFNotFoundError` for absent/invalid members, and `CTFPermissionError` for denied actors. Participant team views already map through `ctf_error_response` (state conflict is 409). Organizer views use `_CtfApiError`/`_raise_*`; `shared.api.errors` owns `{error: {code, message, request_id?}}` and DRF errors. Translate expected domain failures deliberately; keep policy outages as safe 503 responses. No new exception hierarchy, raw model/DB/provider text, or exception details in public responses. |
| Audit and observability | Organizer `_audit.audit_admin_event_mutation` is the database-only mutation precedent; audit and mutation share a transaction so strict audit failure rolls back. Preserve the shared policy/audit provenance path. Do not use the external-effects intent/outcome workflow here. Reuse module loggers, bounded operation/actor/team/target IDs, `shared.log_sanitize.safe_log_value`, and shared request IDs. No raw request bodies, invite codes, credentials, flags, or new audit store. A pre-commit log is not proof of a committed mutation. |
| Configuration, secrets, host/runtime | This is an in-process Django/DB change. Existing event `team_mode` validation and configuration-free authorization actions suffice. `config/_product_env.py`, `_env_manifest.py`, `env-manifest.json`, installation parsers, secret bindings, OS argv/env, workers, cloud IAM, Helm and Terraform need no new input or change. Introduce no secret, subprocess, shell argument, external transfer, deployment flag, or runtime bypass. |
| Repository enforcement | Root `.ground-control.yaml` (`github_repo` is canonical), `.gc/plan-rules.md`, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR registry/exceptions, pre-commit, and `.github/workflows/_quality.yml` remain authoritative. Keep writes within CTF services and cross-domain calls through existing bridges/facades. No dependency, guard exception, private scenario material, or copied workflow. |

## Concurrency and integrity conditions

Authorization against a previously loaded `participant.team` is stale after
organizer reassignment. Recheck captain authority and target membership against
locked current rows before changing captaincy or dissolving. Sharing only the
assignment statement while leaving participant transfer outside that serialization
would allow a former captain to overwrite an organizer's reassignment. Member
removal, leave, join/switch, transfer and disband can also race with selection;
successful assignment must not knowingly leave a departed target as captain.
An idempotent no-op still requires current authorization and valid membership.

The existing team row lock plus an `exists()` check does **not** alone make
dissolution atomic with recording a solve. `submission._record_submission_locked`
locks participant then challenge, inserts the submission, and scoring may lock
the team. `scoring._maintenance.recompute_team_score` explicitly requires
participant-before-team ordering. Team join/leave/disband currently take team
before participant writes, an opposing order. A solve can be uncommitted when
disband reads, or deadlock when disband later updates members. Dynamic decay also
recomputes multiple participants and teams. Do not add team-then-participant
locks and call the race solved, or move external flag verification under locks.

The implementation design must establish a bounded, consistent serialization
protocol across the affected membership, dissolution, assignment and submission
writers, including revalidation of any membership snapshot taken before locking.
Use existing transactions/locks; a global mutex, new queue, or speculative retry
framework is unnecessary. Prove on PostgreSQL that a solve committed before
dissolution's serialization point prevents deletion, and that dissolution winning
first makes the existing locked submission membership gate refuse. Avoid nullable
`select_related("team")` outer joins under `FOR UPDATE`. SQLite cannot prove these
properties. Broader membership defects (for example, switching teams while still
captaining the old one) are existing risks, not permission for an unrelated rewrite.

## Evidence required from implementation; non-goals

Reuse `tests/ctf/test_team_api.py`, `test_team_submission.py`,
`test_event_staff_api.py`, `test_drf_api_token_access.py`,
`test_unified_authorization.py`, `test_authorization_operation_map.py`, and the
PostgreSQL pattern in `test_services/test_submission_concurrency.py`. Cover direct
services and HTTP/SPA behavior: correct zero-point solves refuse dissolution;
incorrect attempts/awards alone allow it; ineligible members' correct submissions
still count; lone-captain leave cannot bypass it; denial preserves membership,
captain, deletion and invalidation state. Make the stated soft-delete and current
membership semantics explicit in evidence.

Prove owner/authorized co-organizer reassignment, unrelated-event and insufficient
capability/scope denial, policy unavailability, malformed/missing/out-of-team
targets, stale captain/null captain recovery, concurrent submission/dissolution
and transfer/removal/reassignment, and audit rollback. SPA evidence must show an
accessible organizer action, pending/error handling, refreshed captain state and
cache invalidation of every affected organizer/participant team projection.
Keep invite secrets out of organizer responses and non-captain refreshes.

ADR-019 requires real first-party service behavior; mock only external boundaries
such as policy provider I/O, not captain/solve helpers. Targeted mutation evidence
should detect removing the solve guard, the last-member guard, membership/event
checks or organizer action check. Run targeted tests locally; full suites belong
in CI. Retain the ADR guard, Ruff and relevant import checks, generated-contract
drift checks, frontend typing and targeted component tests.

This preflight changes guidance only. It does not implement the feature, write
tests, change requirement status/traceability, publish a PR, or deploy anything.
The implementation does not redesign scoring/history, restrict all membership
changes after solves, repair historical captain rows, expose a general team CRUD
API, expand staff powers, alter event ownership, or add notifications. Any larger
transactional correction necessary to satisfy the race invariant must remain
explicit and bounded rather than hidden inside an endpoint patch.

## Implementation design

The organizer action selects a participant on their detail page.
The request names the persisted team and the selected participant UUID.
The response returns captain state without invite codes.
The detail projection adds stable team and captain IDs.

Team mutations lock current members in primary-key order before locking the team.
Member locks use NOWAIT and return a state conflict when a member is busy.
This prevents a cycle with dynamic scoring, which can hold another member first.
They then compare current membership with the snapshot.
A changed snapshot produces a state conflict with no writes.
Join locks the joining participant before the target team.
Submission already locks its participant before maintaining team scores.
These locks serialize dissolution with submission without external verification under locks.
Captain authority is checked again after locking.
This protocol preserves the participant-before-team scoring order.
Tests must prove the protocol on PostgreSQL.

References: Django 6.0 QuerySet API, select_for_update and exists,
https://docs.djangoproject.com/en/6.0/ref/models/querysets/ .
DRF permissions, object-level checks,
https://www.django-rest-framework.org/api-guide/permissions/ .
No deployment or ADR change is required because existing service and policy boundaries remain intact.

The browser is outside the server trust boundary.
The credential and event-policy checks protect team ownership against forged IDs.
The service verifies membership again to protect against stale browser state.
The database transaction protects captain changes and the strict audit record together.
Domain conflicts preserve the team and its member references.
No invite secret crosses the organizer response boundary.

## Delivered behavior and evidence map

The solve restriction is implemented by `_require_no_solves` in `ctf/services/team.py`.
Both disband and last-member leave invoke the restriction before changing membership.
The zero-point API regression and cached-score tests cover this criterion.

Organizer reassignment uses `reassign_captain` and the organizer `TeamCaptainView`.
The participant detail card offers assignment to actors with team capability.
API tests cover success, unrelated actors, and targets outside the team.
The component tests cover the action, errors, and capability visibility.
PostgreSQL tests cover both orders of submission and dissolution.

The protocol can refuse a busy team before a concurrent submission commits.
The caller retries after refreshing state.
There is no automatic retry or discarded write.

Review strengthened the concurrency evidence.
The solve-first test requires NOWAIT refusal before committing the solve.
The dissolution-first test observes the submission's PostgreSQL lock wait before committing dissolution.
This forces database overlap instead of relying on thread scheduling.
Mutation checks remove member locking and locked membership validation independently.

The authorization surface inventory also records the new team endpoint.
Its persisted team locator maps to `event.manage_teams` on the event.
The historical baseline remains unchanged.
