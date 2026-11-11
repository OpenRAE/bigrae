# CTF real-time notifications preflight (#665 / CTF-802)

> **Historical implementation record.** This issue-scoped preflight is not
> current-system authority. See the [current-state handbook](../technical/architecture.md)
> and accepted, superseding ADRs.

Assessment: 2026-10-31, baseline `f526e68fa`. Scope: design guidance before
implementation, not an implementation plan or a delivery/activation claim.
Application paths below are relative to `shifter/shifter_platform/`; other
paths start at repository root.

## Decision and current constraints

Extend the existing CTF communication ledger and shared notification transport.
[ADR-051](../adr/index.yaml) R6/R12/R13, [ADR-065](../adr/065-retire-legacy-ctf-notification-writes.md),
and the [communication boundary documentation](../technical/shifter_platform/ctf-communications.md)
already settle ownership, durable availability, receipts and retirement. No new
ADR, notification framework, socket endpoint or exception hierarchy is needed.

The supplied issue's older description is not the current wire contract:

- `ctf/services/notification/realtime.py::_reference_payload` projects every
  non-communication payload to `{"kind": "refresh"}`. Communication frames
  contain only validated snapshot/intent UUIDs. Projection runs before storage
  and again before live send/replay, protecting retained legacy rows too.
- `frontend/src/features/ctf/CtfWorkspaceLayout.tsx` accepts only those two
  shapes. A refresh invalidates queries; only a communication reference produces
  the content-free inbox toast. Publishing `challenge_released`, `first_blood`
  or a rank payload alone cannot satisfy a visible notification criterion.
- `publish_event_notification` supplies the **event's UUID** as the shared
  delivery identity. The unique key is `(recipient, topic, notification_type,
  event_id)`, without `kind`. All notices for that event/recipient therefore
  converge on one row, whose payload and delivered state are not replaced.
  Adding more calls to this helper does not establish distinct replayable notices.
- `release_challenge` changes visibility without a notice. The first-blood
  publisher is in `submission._emit_solve_events`. Announcements already have
  durable ledger release, inbox availability and reference wake-ups; do not add
  a second announcement publication workflow.
- `WEBSOCKET_NOTIFICATIONS_ENABLED` defaults to false. Its three enablement,
  replay and retention settings are absent from `_EXPLICIT_BINDINGS` and
  `config/env-manifest.json`, and have no first-class installer/chart binding.
  `scripts/stack-smoke/stack_smoke.sh` opts in for testing; that is not deployment
  activation. `prune_notifications` exists, but no deployment schedules it.

## Reuse and domain boundaries

| Concern | Canonical incumbent and consequence |
| --- | --- |
| Durable participant notice | `communication/campaigns.py` (`CampaignDraft`, `create_system_event_campaign`), `scheduling.py`, `release.py`, `materialize.py`, and the existing campaign/intent/snapshot/receipt/attempt models. A notice requiring offline availability enters this ledger with explicit `in_app` selection. Its snapshot UUID is its inbox identity. |
| Trusted source and occurrence | `notification/_organizer.py` demonstrates stable server-derived campaign/occurrence identity and a scheduled declaration committed with a source transition. Reuse the admission/scheduler path, not its organizer audience. `notification/ledger.py::stage_notice` is currently email-only; calling it unchanged would not provide an in-app notice. |
| Transport | Keep `ctf_event` / `ctf:event:<uuid>`, `register_ctf_notifications`, `publish_communication_wakeup`, `shared.notifications`, `SharedNotificationConsumer`, and `notification_user_topic_group`. The existing in-app adapter maps the snapshot UUID to shared replay identity and returns a closed `DeliveryOutcome`. |
| Source transitions | Challenge services own scheduled **and manual** visibility changes; `CTFScheduledTask` and `run_ctf_scheduler` own timing, claims and retries. Submission/scoring, award, participant moderation, team membership and event lifecycle services own their respective changes. No controller-only hook or generic model signal can substitute for those owners. |
| Ranking | `ctf.services.scoring` owns materialized maintenance, exact cold reads, shared-rank ties, null-last ordering, dynamic decay and team deduplication. `ranked_participant_q` differs deliberately from `viewing_participant_q`. A participant who can read does not necessarily rank. |
| Presentation | Existing inbox API/services, `api/ctfInbox.ts`, typed `apiFetch`, TanStack Query, `CtfWorkspaceLayout`, `Toast` and `MarkdownContent`. Keep principal/event cache separation, bounded pages/toasts, non-blocking accessible status, and authenticated refetch. Never render socket content. |

`NotificationType` on legacy `CTFNotification`, communication `NoticeKind`
(including email-template selection), the shared bus registration name and a
domain occurrence kind are different concepts. Do not extend a retired enum or
add an email template just to recognize a browser notice. Use the existing closed
communication contracts; extend only the discriminator whose actual owner needs
the new behavior. `AppConfig.ready` is transport wiring, not a communication
trigger/audience/channel extension registry (ADR-051-R11).

## Correctness and extensibility seams

Participant-visible notices should use fixed, non-secret text and authenticated
links to current challenges, scoreboard or inbox. Detailed rank/challenge facts
come from authorized reads, so retained messages cannot become an alternate
route to hidden challenges, frozen results, flags, answers or participant PII.
First-blood and release eligibility must honor the owning challenge visibility,
release and participant-availability rules; an event topic is not permission to
read every challenge. Keep organizer-only alerts on their existing recipient kind
and inbox; never manufacture organizer participants or broadcast their content.

The domain seam is a validated **source occurrence plus explicit recipient scope
and channels**, feeding existing admission. Stable identity distinguishes a
challenge release occurrence, a first correct submission and a committed ranking
change; retries use that same identity. Event UUID alone collapses unrelated
notices; a fresh random UUID on every retry duplicates them. Participants without
a browser user ID retain inbox availability through their participation; a missing
SQL user means no socket candidate, not no message. Do not widen channels to email
or bypass system authoring budgets: the existing rate-budget exemption is reserved
for scheduled organizer alerts, not high-volume participant rank traffic.

For position changes, use the event's canonical participant-facing board selected
by `team_mode`, with competition-ranking ties. A score change is not necessarily
a position change, and one solve can move many other participants. Dynamic decay,
award creation/deletion, qualification/visibility changes and team membership
changes also affect positions. `get_participant_rank` is a live individual rank;
it does not apply board freeze or publication policy and cannot alone authorize
a notification. Organizer monitoring deliberately ignores freeze and must not
feed participant notices.

Compare the participant-visible projection governed by `ctf/api/views.py`
(`scoreboard_visibility`, `is_scoreboard_frozen`, freeze cutoff) and the scoring
service. Hidden or frozen live changes must not emit a side channel saying a
position moved. Unfreeze/publication transitions need reconciliation against the
newly visible board. Notify only affected eligible recipients, including affected
team members in team mode. An initial connection is not itself a position change.
Keep **board scope** an explicit input at the scoring boundary (event now;
bracket/team view when supported), without a second ranking algorithm or a new
general board framework. This leaves the next board variation possible without
rewriting transport, inbox or deployment artifacts.

The implementation must establish a consistent comparison of committed visible
positions under concurrent changes. Reading an old board, committing a solve,
then independently reading a new board does not prove which transition caused
which notice. Respect existing lock ordering and SQL constraints; no remote
authorization or transport I/O while holding producer locks. Avoid one full-board
recompute or one rank query per recipient on every solve: preserve the materialized
hot path and bound recipient work through existing admission/backpressure and
delivery batches. Rebuilds and no-op/retried releases must not manufacture changes.
If updates are coalesced, describe the visible change semantics honestly; do not
claim every intermediate position was delivered.

Persist the notice declaration or recoverable handoff with the authoritative
source change. `transaction.on_commit` can schedule an optional wake-up; alone
it leaves a crash window that loses an offline notice. The source operation must
not roll back because Redis is unavailable, and failed declaration/admission
must remain recoverable under existing ownership. The organizer-alert pattern
retains failed declarations on scheduler work; it is not a license to swallow a
failure for a source with no later retry. The existing submission emitter runs
after an inner atomic block, which may still be inside an outer transaction.
Do not copy that timing as proof of an outermost commit.

## Cross-cutting gates the design must pass

| Layer | Required use and evidence |
| --- | --- |
| Browser and socket authentication | Preserve `config/asgi.py`: `AllowedHostsOriginValidator`, session middleware, `CredentialSessionWebSocketBoundary`, `CTFAccountWebSocketBoundary`. Use the current human `CredentialContext`; retain idle/input/output revocation and temporary-account/password-change gates. Same-origin `wss` in deployed HTTPS; no API token or credential in URL/query/frames. |
| Topic and live authorization | Reuse `validate_topic`, UUID event resolution, `_can_subscribe`, `authorize_event_projection`, native policy and exact live participation. Candidate user IDs are routing only. Subscription, each live send, replay and inbox reads independently reauthorize; deny/provider outage must not fall back to SQL creator flags, staff groups, cached membership or a service principal's responsible human. Preserve recipient filtering and hashed per-user/topic groups. |
| Admission, parsing and storage | `communication_contracts.py` owns closed audience/trigger/channel/content shapes, byte/cardinality bounds and safe Markdown/link policy; `campaigns`, `admission`, `release` own current source authority and scope. Reuse model `full_clean`, immutability and database constraints; bulk writes bypass model validation. Event/account/workspace placement follows current `ResourceScope` services; workspace membership alone grants no CTF authority. Synthetic fixtures only. |
| Payload and UI validation | Keep `_reference_payload` on persistence **and** send/replay and the SPA frame classifier. Malformed/legacy/unknown content cannot become a toast. Resolve identifiers through the existing session-authorized API, generated DTOs and safe renderer/CSP. No handwritten duplicate inbox schema, HTML toast, remote media, cross-tab content or browser persistence of private notices. |
| Error and evidence boundary | Reuse `CTFError` / `CTFCommunicationError`, closed delivery outcomes/reasons, `shared.api.errors`, `shared.errors`, `shared.log_sanitize.safe_log_value`, configured logging and `shared.audit`. Public errors are authored bounded text with accepted request IDs, never `str(exc)` or provider/database dumps. Correlate event/intent/snapshot/attempt IDs and counts, not bodies, coordinates, flags, tokens or private pack details. Audit is not queue state; a caught exception is not delivery success. |
| Root deployment configuration | `installation.loader.load_root_config` rejects duplicate/merge YAML keys and dispatches closed backend validation (`GcpBackendSettings`, `AwsSettings`). Use the backend bundle/shared policy conventions and published contract generation for an operator-facing option; do not invent a permissive settings map or new configuration file. One enablement decision and bounded retention/replay/prune parameters must render consistently for portal, scheduler and worker. Keep disabled-by-default local behavior. |
| Runtime env and chart shapes | Reuse installation renderers, `runtime_inventory{,_gcp,_aws}.py`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/aws_eks.py`, and chart `values.schema.json`/`shifter.platformRuntimeEnv`/`configmap-runtime.yaml`. Boolean env values must render as strings the Django parser understands (`true`/`false`, not `1`); integers require positive operational bounds. `_env_int` checks syntax only and the shared bus clamps minima only. Update `_EXPLICIT_BINDINGS` and regenerate the env manifest rather than hand-editing it. Renderer-owned GCP keys belong in generated values, not committed profile overrides. The GCP overlay's closed allowlist is not a generic settings ingress. |
| Secret and OS boundary | Notification controls are non-secret ConfigMap data. Reuse `entrypoint.sh` secret hydration and `config._channels` / `config._redis` TLS/AUTH/CA validation; add no secret store or credentials. Keep Redis URLs/passwords/CA and session proof out of argv, shell interpolation, rendered ConfigMaps, diagnostics and logs. Use existing stdin/private-file/secret-reference transports if deployment tools need sensitive inputs. No new public port, cloud service, permission or participant-supplied URL is needed. |
| Kubernetes/runtime boundary | Use the existing chart workload, identity, health, shutdown, restricted security-context and network-policy conventions for whichever process owns pruning. Notification-only settings need no provisioner forwarding or permission. `shared.cloud.sensitive_env.split_env` and `validatingadmissionpolicy-provisioner-jobs.yaml` are separate gates if a Job environment changes; never widen their allowlists to pass unrelated portal knobs. Account for rollout/readiness and AWS/GCP workload inventories when adding any scheduled runtime. |

## Replay, retention and enablement limits

The shared bus is bounded transport replay, not the durable inbox or a read
receipt. It marks `delivered_at` after a socket write, without a browser ACK;
multi-tab/racing sends can duplicate hints. Replay takes only the first
`WEBSOCKET_NOTIFICATION_MAX_REPLAY` pending rows per subscription and has no
pagination/drain protocol. TTL expiration can discard hints. Offline guarantees
therefore come from retained snapshots/receipts and authenticated inbox
reconciliation, not a promise of exactly-once or unlimited socket replay.

`api/ctfInbox.ts` already reconciles on focus/network reconnect, cross-tab hints
and a bounded poll. The CTF socket hook currently opens once per event and has
no close/reconnect loop. Reuse the bounded backoff/jitter, terminal-close and
cleanup conventions of `mission-control/useRangeStatusSocket.ts` if adding
reconnection; use current `shared.enums.WebSocketCloseCode`, not its stale
`cyberscript` comments. Resubscribe/reconcile after reconnect, tolerate replay/live
overlap, and discard late callbacks, timers, cached content and toasts when
principal/event authority changes. Repeated hints must not create repeated
visible messages or mark read/dismiss/acknowledge.

Enable only a supported configuration that also runs verified pruning and uses
shared Redis across portal/worker processes; an in-memory layer cannot connect
them. Reuse `prune_expired_notifications` / `prune_notifications`; the current
single bulk deletion needs bounded work appropriate to sustained fan-out. Use
existing pruning process/heartbeat conventions rather than a new scheduler.
Prune expired delivered **and** undelivered rows; TTL filtering alone does not
delete them. Ledger content retention (`communication/retention.py` and
`prune_ctf_communications`) and audit retention remain separate owners. Do not
extend content retention to compensate for an undrained socket queue.

Measure failures/backlog/oldest-due age and pruning success/counts through existing
worker metrics/logging, and Redis readiness through existing health checks and
posture logging. Process liveness alone does not establish successful pruning or
delivery. Disabling the bus must still stop recipient enumeration, row creation
and `group_send` early while preserving the durable inbox. A rendered flag or
an in-process test is not evidence of cross-process delivery.

## Verification boundaries and non-goals

Extend existing notification, communication, challenge-release, scoring and
scheduler tests, `tests/ctf/test_native_notification_authority.py`, real ASGI tests
under `tests/integration/asgi/` (including Redis multiprocess coverage), and the
workspace/inbox/fake-WebSocket frontend tests. Evidence must cover independent
occurrences versus retries, rollback/outer commit/crash recovery, simultaneous
rank changes, all rank-changing owners, ties/team/bracket/freeze/hidden boards,
revocation during replay/final send, expired/more-than-one-page replay, multi-tab
duplicates, disabled/outage behavior, no-op releases and bounded load/pruning.
Use PostgreSQL for locking/concurrency proof. Negative tests inspect stored
payloads, frames, logs, error envelopes, rendered env and argv for disclosure;
mock external boundaries rather than bypassing first-party services (ADR-019).

Use existing installation/runtime-inventory and chart tests for configuration
parity and invalid inputs; regenerate OpenAPI/client types only if their owning
HTTP contract changes. Required checks remain `adr_guard --all --level ci`, and,
when their files change, import-linter, Python lint/format, Helm/kube-linter/pinned
kubeconform, TFLint and actionlint as specified in `AGENTS.md`. Registry checks
alone do not prove runtime acceptance. Keep CTF-802's current requirement status
and delivery traceability unchanged during preflight; any later issue/PR uses
`.ground-control.yaml`'s canonical repository, not the supplied historical link.

Non-goals: implementing CTF-802 here; enabling a live deployment; a second socket,
outbox, inbox, retry worker or scheduler; resuming retired `CTFNotification`
writes; changing scoring/ranking or organizer visibility; email/push/SMS opt-in;
new RAES or extension contracts; a browser ACK protocol or exactly-once claim;
unbounded replay; and unrelated configuration/identity redesign. The following
implementation owns source notices, correct recipient-visible rank changes,
reference delivery/UI behavior, and a complete supported opt-in with retention.
