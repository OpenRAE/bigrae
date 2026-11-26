---
id: CTF-407
title: "Challenge Statistics"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.503444Z
updated_at: 2026-10-28T00:00:00Z
---

# CTF-407: Challenge Statistics

## Statement

The system should display per-challenge statistics including: total solve count, solve percentage (solves / total participants), number of submission attempts, and first blood holder. Statistics shall be visible to organizers at all times and optionally visible to participants (configurable per event). Statistics shall update within 30 seconds.

## Rationale

Challenge statistics help participants gauge difficulty (low solve rate = hard) and help organizers identify broken or overly simple challenges mid-event. For organizers, statistics inform decisions about releasing hints or adjusting point values during long-running events. (CTFd shows solve counts on challenge cards.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/` (get_challenge_statistics() - per-challenge stats (solves, solve rate, attempts, first blood))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/` (CTFChallenge.first_blood property and CTFChallenge.solve_count property)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin/` (CTFChallengeAdmin with solve_count_display annotation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_stats.py::get_challenge_statistics` (Challenge statistics service - solve count, solve percentage, attempts, first blood)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring_statistics.py` (Challenge statistics tests - solve percentage, attempt count, solve count, first blood, zero-roster behavior)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/event.py` (participant_challenge_stats_visible - per-event participant visibility setting, default off)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/projections.py::_participant_challenge_stats` (Participant challenge statistics, gated by the event setting)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/serializers/_common.py::ChallengeStatisticsSerializer` (Shared participant and organizer statistics serializer)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_api.py` (Participant statistics disclosure - both states of the event setting)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
- IMPLEMENTS → GITHUB_ISSUE `522` (Issue #522 - per-event participant visibility for challenge statistics)
