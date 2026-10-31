---
id: CTF-802
title: "Real-Time Notifications"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:23.323699Z
updated_at: 2026-10-31T00:00:00Z
---

# CTF-802: Real-Time Notifications

## Statement

CTF events could deliver real-time in-app notifications using the platform's WebSocket infrastructure (PLAT-105). CTF-specific notification types include: new challenge released, announcement posted, scoreboard position change, and first blood achieved. Notifications shall be displayed as non-blocking toasts or a notification panel. Participants who are not connected shall receive notifications upon next connection.

## Rationale

Real-time notification delivery is a platform capability. Mission Control already has WebSocket consumers. CTF registers its notification types with PLAT-105 rather than building a separate WebSocket layer.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#665` (CTF-802: Real-Time Notifications)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification/live.py` (Per-event live kinds, live-notice and position-reconcile tasks, nameless inbox notices (ADR-072))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification/realtime.py` (Closed socket projection and per-occurrence live hints on the PLAT-105 bus)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/_live_notifications.py` (Event live notification kind default and validator)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/ctf/CtfWorkspaceLayout.tsx` (Gated notification socket with bounded reconnect and fixed-text toasts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/ctf/admin/EventFormPage.tsx` (Organizer live notification kind selection)
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/notification-prune-cronjob.yaml` (Scheduled bounded prune of expired notification rows)
- IMPLEMENTS → CODE_FILE `scripts/gcp/render_runtime_env.py` (GCP deployments turn on the live notification capability)
- IMPLEMENTS → ADR `docs/adr/072-live-ctf-notifications-per-event.md` (Live CTF notifications are per-event and cost nothing when unused)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_live_notifications.py` (Zero-work gate, release and first-blood notices, position reconcile, projection, prune, API, scheduler execution)
- TESTS → TEST `shifter/shifter_platform/frontend/src/features/ctf/CtfWorkspaceLayout.test.tsx` (Socket gating, hint toasts, reconnect and terminal close codes)
