# Native CTF—Smoke & Validation Protocol

Use this how-to guide to qualify a synthetic CTF event on an authorized tenant.
It covers organizer and participant journeys, scoring, teams, and participant ranges.
The current workspace uses SPA pages and the `/api/v1/ctf/` API.
Legacy `/ctf/api/` mutations are not current interfaces.

A source test or successful deployment does not prove a live event.
Record the exact release, backend, test actors, expected results, and observed results for each qualification run.
Keep private operational evidence in the operator's evidence location.
This documentation rewrite does not execute the protocol or qualify a tenant.

## Setup

1. Obtain authority for the selected tenant, test event, ranges, and workload.
2. Confirm deployment health and the exact source revision.
3. Prepare synthetic event content and at least two distinct participant actors.
4. Grant organizer authority through the supported native administration route.
5. Confirm the selected event's time window, capacity, scenario, and cleanup policy.

Use the [organizer guide](../features/ctf-organizer-guide.md) for current creation and administration tasks.
Use the [participant guide](../features/ctf.md) for the participant journey.
A staff flag or historical group name alone does not prove current authorization.

### Running management commands

Use the selected deployment's supported management-command route and runtime configuration.
A new container process does not automatically inherit secrets loaded into another process.
Do not print secret values or place them in command arguments.
Do not use direct SQL writes to bypass service validation or authorization.
Use the [deployment handbook](../technical/handbook/gcp-github-less-deployment.md) for the deployed runtime and its operator boundary.

### Accounts you will need

| Actor | Required state |
| --- | --- |
| Organizer | Authorized for the synthetic event's native parent scope |
| Participant A | Admitted to the selected test event |
| Participant B | Separately admitted for team and concurrency checks |

Use normal authentication for each actor.
Identity-provider login can require MFA; temporary CTF accounts use their supported participant authentication route.
Do not share an administrator session across participants.

## Part 1—Organizer journey

### 1.1 Reachability **[CLI/DB]**

Check the deployment's health route through its supported operations procedure.
Open `/ctf/admin/events/` as the organizer.
Confirm the application loads and an unauthorized actor cannot administer the event.
An HTML response alone does not prove authorized API operations.

### 1.2 Create an event **[Browser]**

1. Create a synthetic event in the intended parent scope.
2. Set its start, end, participant limit, team-size limit, and scoreboard-freeze time.
3. Save it and reopen the detail page.
4. Compare the returned values with the submitted values.
5. Confirm the lifecycle schedule through the authorized event projection or management route.

Avoid selecting the newest database row as an implicit target.
Retain the exact test event identifier for later checks and cleanup.

### 1.3 Add challenges, flags, prerequisites **[Browser]**

1. Create a static-flag challenge, a multi-flag challenge, and a challenge with `max_attempts`.
2. Add the required flags. Give the multi-flag challenge two valid flags.
3. Make challenge B require challenge A.
4. Add a hint with a nonzero penalty.
5. Release the challenges or schedule their release.
6. Reopen the challenge details and compare flags, prerequisites, release state, and hint penalty.

### 1.4 Invite participants / open registration **[Browser]**

Admit the synthetic actors through the organizer workflow.
If testing public registration, use its explicit event registration link.
Confirm admission and lifecycle state when the event starts.
Do not infer admission from an email being sent.

## Part 2—Participant journey

For a temporary participant account, use **Manage password** in the organizer interface:

1. Generate a password and retain it only in the private test credential location.
2. Dismiss the dialog and reopen it. Confirm the password is no longer displayed.
3. Confirm participant detail and invitation resend do not reveal or email the password.
4. If needed, set another policy-compliant password without changing the event's shared-password policy.
5. Sign in through the participant route and complete the required initial password change.

### 2.1 Register & view challenges **[Browser]**

Open `/ctf/` as Participant A and select the admitted event.
Confirm challenge B stays locked until A is solved.
Confirm an actor without event admission cannot read private challenge content.

### 2.2 Submit flags & scoring **[Browser + CLI/DB]**

1. Submit a wrong flag for challenge A and verify rejection and attempt recording.
2. Submit the correct flag and verify one solve, the correct score, and challenge B unlocking.
3. Use the penalized hint on another challenge.
4. Solve that challenge and verify the penalty in the resulting score.
5. Compare the participant projection, submission evidence, and scoreboard through authorized reads.

The solve count must equal distinct solved challenges.
A repeated accepted transport request must not create another scoring effect.

### 2.3 Scoreboard **[Browser + CLI/DB]**

Open `/ctf/scoreboard/` and compare the selected event's scores.
After its freeze time, submit another valid solve.
Confirm the visible frozen board excludes that solve, including while the event is paused.

### 2.4 Participant range lifecycle **[Browser + CLI/DB]**

Launch the selected scenario through the participant range page.
Observe the authoritative lifecycle until the range becomes usable or reports failure.
Use the supported Stop, Start, Restart, and Destroy actions where the selected backend supports them.
Verify each effect on that participant's exact range.

Use [range functional smoke](range-functional-smoke.md) to verify terminal and Guacamole usability.
A ready projection or open port alone is insufficient.
Do not edit provider identifiers or range records to manufacture a test state.

## Part 3—Regression guards

These are verification objectives, not claims that the historical defects remain open.
Run concurrency cases in an isolated test deployment with approved load and distinct actors.
Use current mounted endpoints, normal sessions, CSRF protection, and the current API reference.
Do not replay the retired `/ctf/api/` examples.
Targeted source regressions belong in the owning test modules; PostgreSQL concurrency evidence belongs in its CI lane.

### G-A. TOCTOU on count/uniqueness invariants

| Check | Trigger | Required result |
| --- | --- | --- |
| Double-score | Concurrent correct submissions for one challenge | Exactly one correct scoring effect |
| Attempt cap | Concurrent wrong submissions to a capped challenge | Attempts do not exceed `max_attempts`; cooldown remains enforced |
| Team overflow | `team_size_limit+3` joins using one team code | Membership does not exceed the limit |
| Prerequisite cycle | Concurrent A→B and B→A prerequisite changes | No cycle or duplicate edge |
| Participant cap | Concurrent admissions at `max_participants-1` | Admission does not exceed the cap |
| File cap | Concurrent uploads at `MAX_FILES_PER_CHALLENGE-1` | File count stays within the cap; order values remain unique |

The source submission tests are in `tests/ctf/test_services/test_submission_concurrency.py` under the platform package.
Migration and constraint checks supplement behavioral evidence; constraint presence alone does not prove the request boundary.

### G-B. Team scoring distinctness

Have both participants solve the same challenge on one team.
The team score must count its points once, including frozen-score recomputation.

### G-C. Range lifecycle pk vs range_id

Verify operations target the owning range through its current lifecycle service.
The range's database key and provider/runtime identifier are different contracts.
Confirm destruction completes without an orphan; request acceptance alone is insufficient.

### G-D. Cross-event authz isolation

Admit one actor to two eligible events, then withdraw authority from one.
Verify the actor retains only the independent authority for the other event.
Check the current native policy boundary instead of a legacy platform-wide group.

### G-E. Scoreboard freeze under pause

Freeze the selected event, record a later solve, and pause it.
Confirm both the page and API projection retain the frozen result.

### G-F. Event-task reschedule on window edit

Change the active event's end from T to T+1 hour.
Confirm its pending end task moves to T+1 hour with no stale pending task at the original time.
Use the owning schedule read path; do not change task rows directly.

### G-G. API error contract

| Check | Trigger | Required result |
| --- | --- | --- |
| Invalid participant row | Non-object entry such as `{"participants": ["x"]}` | HTTP 200 with a per-item error and no imported participant for that row |
| Invalid import list | A non-list `participants` value | HTTP 400 validation response, never an unhandled HTTP 500 |
| Participant range selection | Actor eligible for more than one event | Projection matches the selected eligible event and excludes ineligible rows |
| Empty multi-flag configuration | Remove all accepted flags, then submit an old flag | Submission rejected; `ctf.services.challenge` logs an error stating every submission will be rejected |

Check the operator log for the empty-flag case; the participant receives an ordinary rejection.

Use [interface reference](../reference/interfaces.md) for current routes, authentication, and error envelopes.

## Part 4—Teardown

1. Destroy only the exact ranges created for this qualification.
2. Observe their terminal cleanup state through the supported lifecycle and provider evidence.
3. Investigate unknown cleanup before retrying.
4. Retain the required audit and recovery evidence.
5. Remove the synthetic event through the authorized organizer procedure after its cleanup conditions are satisfied.

Do not run wildcard deletion against a shared tenant.
Use the [recovery runbooks](../runbooks/index.md) when cleanup fails.

## Known open issues

This anchor is retained for existing links to the original defect catalog.
The original catalog named issues #1135 through #1149, excluding #1136.
Their categories remain represented in Part 3.
The catalog is historical context, not a current issue-status report or permission to accept a failing guard.
Consult the [canonical tracker](https://github.com/OpenRAE/bigrae/issues) for current status.
A failed current guard requires diagnosis and repair before qualification.
