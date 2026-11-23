---
id: CTF-501
title: "Team Mode Toggle"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.539243Z
updated_at: 2026-11-23T00:00:00Z
---

# CTF-501: Team Mode Toggle

## Statement

The system should support a per-event configuration option to enable or disable team mode. When team mode is disabled, all scoring and rankings shall operate on individual participants. When enabled, a participant who joins a team shares the team's score. A participant with no team competes as an individual and can submit flags and score points. The team mode setting shall be locked once the event transitions to active state.

> #3000 reversed the original clause that required team membership before flag submission. A participant with no team now competes as an individual in team mode. A present team reference must still resolve to a live same-event team.

## Rationale

Not all CTF events are team-based, some are individual competitions. Organizers need a per-event toggle to match the event format. Locking the mode after event start prevents mid-competition confusion where some participants have teams and others do not. (CTFd supports both modes as a per-event setting.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/` (CTFEvent.team_mode field (line 279))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#644` (CTF-501: Team Mode Toggle)
