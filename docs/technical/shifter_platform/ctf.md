# BigRAE CTF

Capture-the-flag is a Django app (`ctf`) layered on the platform's range system. It owns event, challenge, and scoring data.
It orchestrates a dedicated range per participant through existing CMS range services.
It introduces no second provisioning path.

## ADR-066 authorization

The source contract for CTF authorization lives in
`ctf.api.operation_policy`.
It names the registered action and SQL-owned scope locator for all 118 current `/api/v1/ctf/` operations.
It also classifies browser routes, Django admin models/inlines, management commands, scheduled task types, and external service effects. The issue's
baseline was 114
operations; the current published API contains four additional operations.

The browser routes serve an SPA shell; privileged data and effects belong to
the API and service boundaries. Public registration and scoreboard projection
retain their explicit publication checks. Scenario discovery retains the CMS
model-access boundary.

`ctf.services.unified_authorization` composes an active human or service
principal, the credential's exact action ceiling, CTF-owned event scope, and
the shared OpenFGA provider. Event creation checks the selected existing
account, organization, or workspace parent. Individual accounts have no
invented organization or workspace; team and enterprise accounts use an
organization or workspace parent. OpenFGA must show exactly one matching
event parent. The same exact-parent rule covers event-derived ranges.

The SQL authorization inventory includes account- and organization-placed events
in scoped delegation proofs and checks exact event ancestry on direct policy
mutations. Service participant admission and current-event reads already use the shared check;
the participant row and lifecycle predicates remain separate requirements.
Provider failures deny with a bounded unavailable response.

S8 binds those decisions to the production service and API paths. Legacy user
flags, ownership and staff rows no longer substitute for policy decisions.
The policy-aware Django admin disables direct domain writes. This describes
source behavior, not a live deployment.

Staff assignment, removal and ownership transfer retain a versioned effect
plan in `CTFEventAuthorityTransition`. The plan fixes the event, subjects,
scope, provider binding and semantic effect keys before publication. Workspaces
owns the existing mutation journal and readback. An evaluator outage remains
retryable; an explicit denial remains denied. A current authorized administrator
can settle an exact retained plan after a recipient becomes inactive. New
inactive grants and inactive callers remain denied.

`GET /api/v1/ctf/events/{event_id}/staff-members/` exposes an authorized nullable
`pending_transition` receipt with its UUID, kind, recipient, requested role,
creation time and completed/total effect counts. The browser resumes that
command through the existing staff endpoints. It does not expose raw policy
tuples or credentials. See [identity and lifecycle contracts](identity-lifecycle-contracts.md)
for the DFDs, recovery state and lock order.

## Responsibility

- Model CTF events, challenges, flags, teams, brackets, submissions, hints, and
  notifications.
- Validate flag submissions and compute scores and leaderboards.
- Provision and clean up one range per participant from the event's scenario.
- Serve participant, organizer/admin, and JSON API surfaces.

## URL Surface

`ctf.urls` (`app_name = "ctf"`) mounts three groups under `/ctf/`:

| Group | Prefix | Audience |
|-------|--------|----------|
| Public registration | `/ctf/public/events/<event-uuid>/` | Unauthenticated, explicitly published event projection and CSRF-protected request intake |
| Participant | `/ctf/` | Competitors: dedicated login, password change, dashboard, challenges, range, scoreboard, team |
| Organizer/Admin | `/ctf/admin/` | Organizers: events, challenges, participants, teams, brackets, ranges, notifications, analytics |
| API | `/ctf/api/` | JSON endpoints for events, challenges, scenarios |

Participant access uses isolated temporary username/password accounts; organizer views are gated to CTF
organizer roles. The portal sidebar distinguishes participant-only users so the two
surfaces stay structurally separate (see ADR-013).

## Models

Models live in the `ctf.models` package (split from a single module in PR #856);
`__init__` re-exports every public symbol so `from ctf.models import X` is stable. All
inherit `CTFBaseModel` with a `SoftDeleteManager` (soft delete by default).

| Model | Purpose |
|-------|---------|
| `CTFEvent` | Competition: window, scenario, capacity, team mode, throttles, scoreboard policy, cleanup policy |
| `CTFPublicRegistrationRequest` | Minimal event-scoped name/email intake with pending, approved, or rejected disposition; never participant authority |
| `CTFChallenge` | Scored task: category, points, difficulty, release time, prerequisite, target instance/port, tags/topics |
| `CTFFlag` | One or more flags per challenge. Static values are normalized plaintext; regex uses patterns; programmable/HTTP uses validator configuration. |
| `CTFTopic`, `CTFChallengeTag`, `CTFChallengeFile`, `CTFChallengePrerequisite` | Challenge taxonomy, attachments, and unlock graph |
| `CTFBracket`, `CTFTeam`, `CTFParticipant` | Cohorts, teams, and per-user participation |
| `CTFSubmission`, `CTFReceiptConsumption`, `CTFAward` | Flag attempts, durable issuer-scoped signed-receipt replay evidence, and manual point awards |
| `CTFChallengeRating` | Participant difficulty ratings |
| `CTFHint`, `CTFHintUsage` | Optional, point-reducing hints and usage tracking |
| `CTFNotification`, `CTFScheduledTask` | Announcements and scheduled work (legacy aggregate evidence; see Scoped communications) |
| `CTFContentHydrationReceipt` | Digest, object-identity fingerprints, bounded counts, and pristine/drifted state for scenario-managed event content |
| `CommunicationCampaign`, `CommunicationTargetEvent`, `MessageRevision`, `CommunicationIntent`, `RecipientSnapshot`, `DeliveryAttempt`, `RecipientReceipt` | Scoped communications domain (ADR-051). Campaigns have one account, organization, or workspace parent. Content, release occurrences, recipients, delivery commands, and receipts retain their own identities. |

`CTFEvent` records immutable native scope fields for its account, organization, or workspace parent.
The retained scalar `workspace_id` is not a cross-layer foreign key.
Communication campaigns target events with the same exact parent scope.

Flag material is persisted in `CTFFlag` rows, not on the challenge.
Static values are stored as normalized plaintext.
Regex flags store patterns, and programmable/HTTP flags store validator configuration.
Submission checking uses those records.
Protect flag-reading access and exports as sensitive authoring material. A single plaintext `flag` on challenge create/update
is normalized into one static `CTFFlag`; a challenge with no flag rows is
unverifiable (every submission is rejected).

Receipt-capable validators use an immutable server-derived CTF → CMS → Engine
binding and an installation-owned authenticated verifier profile. Verification
runs outside locks; the exact registration and objective mapping are rechecked
inside the scoring transaction, where a durable issuer-scoped consumption row
enforces one-shot use. The generic platform never interprets scenario proof
claims or receives symmetric signing bytes. Receipt attempts persist only a
fixed redaction marker in submission history; legacy flag types preserve their
existing history behavior. See the
[operator and extension contract](../../dev/ctf-signed-receipt-validators.md).

## Services

Flag submission requires a live team in the participant's event when `team_mode` is enabled.
The service checks membership before flag verification and again against the locked participant before recording the submission.
Rejection creates no submission or score change.
The optional `require_team` check preserves team creation, joining, and other actions.

Business logic lives under `ctf.services` (views stay thin):

- `event`, `challenge`, `flag`, `bracket`, `hint`, `award`, `attachment`,
  `notification`: entity operations.
- `participant/`: `lifecycle`, `bulk_import`, `queries`.
- `scoring/`: materialized-leaderboard hot path with an authoritative recompute
  fallback (`get_scoreboard`, `calculate_score`, ranks, stats, timeline, and the
  `recompute_*` maintenance helpers).
- `authorization`, `audit`: access checks and audit trail.
- `public_registration`: closed public projection, event-locked pending intake,
  participant-capability review/disposition, and bounded PII retention.
- `communication/`: the scoped-communications domain (see below): `audience`,
  `campaigns`, `release`, `lifecycle`, `retention`.

### Scenario content hydration

`ctf.services.content_resolution` resolves a deployment-owned scenario
reference through the provider-neutral `shared.cloud.ObjectStorage` protocol.
It performs a bounded head/download with an ETag, generation, or version
precondition, verifies the declared SHA-256 digest before parsing, and removes
temporary bytes in `finally`. Provider errors, object coordinates, validator
configuration, and bundle bodies do not cross the public error boundary.

`ctf.content_bundle` is a closed, data-only
`shifter-ctf-content/v1` contract. It validates resource bounds, challenge
identities and orders, native flag policy, prerequisite references, and the
complete DAG before a database transaction begins. It supports native static,
regex, and HTTPS HTTP validators; it does not execute package code or enable
programmable validators.

Event creation composes the resolver with
`ctf.services.hydrate_event_ctf_content`. The service locks the event and checks ownership and state.
It writes the graph through native challenge/hint/prerequisite services.
One atomic transaction creates the graph, receipt, and strict audit event. An exact pristine replay is a no-op. Foreign rows, changed source
evidence, shape mismatch, or a drifted receipt fail closed.

All native organizer mutation paths mark an existing receipt drifted inside
their transaction. Both manual and scheduled activation require a pristine
receipt whose scenario and digest match current deployment configuration.
Scenarios without a configured content reference retain existing behavior.

The deployment reference catalog is the separate closed contract
`shifter-ctf-content-references/v1`, parsed at startup from private deployment
configuration. This feature does not reuse the RAES package catalog or persist
bundle bodies in scenario/event JSON. See the
[operator runbook](../../dev/ctf-scenario-content.md) for publication, provider
IAM, runtime settings, rotation, and failure recovery.

### Range Provisioning

`ctf.services.range` provisions a range per participant from `event.scenario_id` via
CMS range services, the same path Mission Control uses to launch a range.

- `provision.py`: `provision_participant_range(participant_id, *, actor)` checks
  the current credential, then locks the event and participant to reserve one
  immutable launch. Provider work follows that commit. Retry resumes the same
  request rather than creating another generation.
- `batch.py`: throttled event-wide provisioning, pacing participant spin-ups.
- `lifecycle.py`, `status.py`, `tasks.py`: teardown, status reads, and task wiring.
- `vpn.py`: resolves the current participant's generation-bound OpenVPN profile
  through the CTF → CMS → Engine service boundary. The participant API uses only `POST /api/v1/ctf/range/vpn-profile/`.
  It checks current event participation and the exact assigned range.
  Session requests require CSRF.
  Delivery has a rate limit, no-store response headers, and an audit event.
- `recovery.py`: `recover_participant_range(participant_id, *, strategy,
  operator, spare_range_instance_id=None)` recovers a destroyed participant range
  (organizer-only). `rebuild` provisions a fresh range through CMS.
  `reassign_spare` consumes an available `CTFSpareRange` from the participant's event pool.
  CMS and Engine transfer its ownership to the participant principal. The intent is persisted as a `CTFRangeRecovery`
  row keyed on participant + old range + strategy; resumption uses the recorded replacement ID and live old-range state.
  A retry duplicates neither the replacement nor its audit row. Recovery always destroys the old range.
  This operation has no forensics-retention choice. Recovery writes one shared audit
  row.
- `spares.py`: `provision_event_spares(event_id, target_count, *, operator=None)` tops up
  an event's prewarmed spare-range pool (`CTFEvent.spare_range_count`), each spare owned by
  the event owner's principal in the event's account scope until consumed.
  `get_event_spare_summary(event_id)` reports pool counts for the admin surface;
  `cleanup_event_spares(event_id)` tears down unconsumed spares and their managed users at
  event teardown. A spare's status reaches `ready`/`failed` via the existing
  `cms.services.range_status_changed` projection (`ctf.signals.sync_ctf_spare_range_status`).

Long waits are broken into heartbeat-touching chunks so the scheduler's liveness file
does not go stale and provisioning stays responsive to shutdown.

### Participant OpenVPN access

The CTF bridge derives a closed OpenVPN capability from the event cleanup deadline and the single participant-access Kali member.
For legacy templates without access declarations, it uses the unique hydrated Kali member. Engine persists it beside the
range; Mission Control ranges and topology without that capability do not create
a VPN edge. Provisioning admits the shared OpenVPN pool (#2480) to that member only when the capability is present.
It stores the participant profile in the provider secret store. The pool asks the portal before it admits
a client and then allows only the member's address and declared ports.

Django persists only a closed, non-secret binding containing the generation, owner,
target, endpoint, profile version, and secret reference. Profile bytes are resolved and validated in memory after the required checks pass.
These checks cover CTF provenance, participant ownership, range status, request generation, and target membership.

The participant range-status projection exposes only
`vpn_profile_available`; it does not expose provider, endpoint, target, or secret
metadata. Paused and non-ready ranges cannot deliver a profile. Destroy removes the
provider material. Ownership transfer is rejected while a participant VPN binding exists.
Clearing a database reference cannot revoke a downloaded credential.
Recovery destroys that generation and provisions another for the replacement owner before it becomes ready.

Certificates remain valid through the trusted teardown deadline, subject to a
397-day maximum capability window that fails before cloud mutation. Each participant holds one live session per range.
A newer connection replaces the previous session.
Destroy, pause, or the deadline disconnects it within one pool heartbeat.
On GCE, only the provisioner reads the CA.
The pool identity reads only its server identity.
The shared range-host identity cannot read VPN secrets.

See [the provider-neutral range substrate](https://github.com/OpenRAE/bigrae/blob/5954ab13763deaba52a257d4ed8bde5bb1402ea6/docs/architecture/provider-neutral-range-substrate.md)
for the ADR-039 contract and [the issue 1695 architecture preflight](https://github.com/OpenRAE/bigrae/blob/5954ab13763deaba52a257d4ed8bde5bb1402ea6/docs/architecture/ctf-openvpn-participant-access-preflight-1695.md)
for the threat model and containment decisions.

### Scoped communications (ADR-051)

`ctf.services.communication` owns the durable communication domain.
The mounted capability includes HTTP authoring, transport workers, participant inboxes, and the browser console.
Campaigns use one exact account, organization, or workspace parent.
Every target event requires current communication authority and the admitted credential ceiling.
Membership alone grants no communication or recipient access.

See the [communication reference](ctf-communications.md) for immutable revisions, audience resolution, release identity, channel acceptance, retention, and receipt contracts.
See the [user guide](../../features/ctf-communications.md) for organizer and participant tasks.


### Notification and restricted scoreboard authority

Notification recipient lists contain candidate human users derived from current
owner and staff principals. Membership and role facts do not authorize delivery.
The notification socket binds the current credential and retains its ceiling
through topic subscription, replay and each delivery. The owning CTF topic
checks current event-read policy or eligible participation; temporary credentials
remain confined to their exact event and lifecycle. Service principals do not
map to a responsible user's browser notifications.

The participants-only scoreboard uses current native event-read authority or
eligible participant read access. Registered viewing participants may retain
read access after disqualification where the existing viewing rules permit it;
banned, deleted and unregistered rows do not qualify. Ordinary participant
credentials also require current participation policy. Public publication and
hidden scoreboards keep their separate publication rules.

### Scoreboard refresh

The SPA participant and organizer scoreboard hooks poll their API read every
15 seconds (`SCOREBOARD_POLL_MS` in `frontend/src/api/ctf.ts`). They also
refetch on window focus and on network reconnect. Thus a scoring event shows
within 30 seconds (CTF-401). A frozen participant board withholds later solves
by design. The ADR-072 `position_changed` hint is optional and only accelerates
the refresh. See the
[design note](https://github.com/OpenRAE/bigrae/blob/5954ab13763deaba52a257d4ed8bde5bb1402ea6/docs/design/ctf-scoreboard-refresh-576.md).

## Scheduled Work

Two management commands operate the event runtime:

- `run_ctf_scheduler`: long-running scheduler that drives batch range provisioning,
  cleanup, reminders, scheduled tasks, participant-account anonymization, and bounded
  public-registration-request deletion, writing a liveness heartbeat.
- `ctf_recompute_leaderboard`: recomputes materialized leaderboard columns
  authoritatively when reconciliation is needed.

## Boundaries

- Public registration is a server-rendered, exact route ahead of the authenticated
  SPA catch-all. Visibility requires an explicit per-event flag, a live workspace
  scope, and `registration` status. The service allowlists event metadata and uses
  `effective_registration_deadline`; the page does not project arbitrary event pages
  or organizer/participant state.
- Anonymous POSTs use Django form validation, CSRF, body/field bounds, and shared source/event/fleet rate budgets.
  They return generic duplicate success and fixed public errors.
  No-store/no-referrer/noindex controls and an event-row lock also apply. Intake has
  no account, invitation, seat, range, webhook, or mail side effect.
- Organizer listing and disposition use the existing `participants` event
  capability and exact event API scopes. Approval delegates to
  `ctf.services.participant.lifecycle.add_participant`; it does not duplicate
  capacity, account, or provisioning policy. Publication and disposition audits
  contain identifiers and closed state only, never submitted PII.
- CTF reaches the range system through CMS/engine **service calls**, consistent with
  ADR-001 (cross-layer access goes through service boundaries). `ctf` is one of the
  recognized layers in the import policy.
- Per-function complexity stays under the Ruff C901 gate (ADR-012); existing
  high-complexity CTF functions carry tracked exemptions.

## See Also

- [CTF](../../features/ctf.md): participant guide.
- [CTF Organizer Guide](../../features/ctf-organizer-guide.md): running an event.
- [Native CTF scenario content](../../dev/ctf-scenario-content.md): private
  publication and deployment binding.
