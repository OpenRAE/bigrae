# ADR-072: Live CTF notifications are per-event and cost nothing when unused

## Status

Accepted 2026-10-31. Specializes ADR-051-R6 for CTF live notifications (CTF-802).
Supersedes the disabled-by-default deployment posture that issue #941 set for
`WEBSOCKET_NOTIFICATIONS_ENABLED`. Issue
[#665](https://github.com/Brad-Edwards/bigrae/issues/665) records the work. The
[design](../architecture/ctf-live-notifications-design-665.md) records the
architecture, the data flows, and the security controls.

## Context

The shared notification bus has a browser consumer in the CTF participant
workspace. No deployment turned the bus on. The server published only first
blood, range ready, and message wake-ups. The socket projection changed every
non-message payload to a content-free `refresh` hint, so no toast showed. The
event-scoped publisher used the event UUID as the replay identity, so later
notices for one recipient collapsed onto one row. Nothing scheduled
`prune_notifications`.

The capability must always be available in a supported deployment. It must do
no work for an event that does not use it.

## Decision

1. **Each event selects its live notification kinds.** `CTFEvent.live_notifications`
   is a closed list: `messages`, `challenge_released`, `first_blood`,
   `position_changed`, and `range_ready`. A new event selects all kinds.
   Events that existed before this change select none. An empty list causes no
   publish, no scheduler work, and no browser socket.
2. **Supported deployments turn on the capability.** The GCP runtime renderer
   sets `WEBSOCKET_NOTIFICATIONS_ENABLED=true`. The AWS EKS root reads the portal
   stack's Redis channel-layer posture from SSM Parameter Store (ADR-018,
   ADR-044-R6). The AWS renderer sets the flag to true only when that posture
   names a shared Redis host. Live fan-out needs one channel layer across pods.
   The Django default stays false, so local and test runtimes stay off. The flag
   is a deployment kill switch, not the cost gate.
3. **Challenge release and first blood are durable inbox notices.** The source
   transaction inserts a scheduler task. The scheduler stages an in-app ledger
   notice with fixed text. The text names no challenge and no participant,
   because a challenge can have prerequisites. First blood is not declared while
   the scoreboard is hidden or frozen, checked again under the event lock when
   the notice is staged.
4. **A scoreboard position change is a content-free socket hint.** Each score
   owner updates the pending reconcile task for the event in its transaction, or
   inserts one when none is pending. The row lock keeps the scheduler from
   claiming that task before the change commits. The scheduler locks the event, reads the participant-visible board once, and
   compares it with the stored notified positions. It sends a hint to each
   changed entry with a score above zero, after commit. Nothing is compared while
   the board is hidden or frozen, or while the event is not running.
5. **Socket payloads stay in a closed set.** The projection admits a message
   reference, `position_changed`, `range_ready`, and `refresh`. Each hint has its
   own occurrence identity. The browser shows fixed text and reads detail only
   through authenticated APIs.
6. **A Kubernetes CronJob prunes expired rows.** It runs the bounded prune
   command on a schedule and forbids concurrent runs. Nothing runs between runs.
   The GCP running-image check treats a running prune pod as a release workload
   and ignores a finished one.

## Consequences

- An organizer controls live notification cost for each event.
- A position hint reports the change since the last reconcile. It does not
  report every intermediate position.
- A crash after the reconcile commit and before the publish loses those hints.
  The scoreboard still shows the current position.
- Bounded socket replay does not guarantee offline position hints. The inbox
  gives the offline guarantee for release and first-blood notices.
- An AWS environment whose portal stack uses in-memory channels has no live
  notifications.
