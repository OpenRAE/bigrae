---
id: CTF-504
title: "Team Invite Codes"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.646275Z
updated_at: 2026-10-28T00:00:00Z
---

# CTF-504: Team Invite Codes

## Statement

The system should generate unique, shareable invite codes for each team that prospective members can use to join. Captains shall be able to regenerate invite codes to invalidate previous ones. Invite codes shall be single-use or multi-use (configurable). Expired or regenerated codes shall be rejected.

## Rationale

Invite codes provide a simple, shareable mechanism for team formation without requiring organizer approval for each join. For Shifter, consultants can share codes via Slack or email to quickly assemble teams before an event. (CTFd uses invite tokens for team membership.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/` (CTFTeam.invite_code - unique field with auto-generation on save)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/team.py` (invite-code use mode, lifetime, deadline, and spent marker)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/team.py` (single-use spend, expiry rejection, and rotation of invite codes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/team_views.py` (optional regenerate settings and never-cache code disclosure)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_team_api.py` (single-use, expiry, rotation, and captain-only disclosure)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_team_captain_concurrency.py` (single-use code admits one winner under contention)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#647` (CTF-504: Team Invite Codes)
