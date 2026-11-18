---
name: ship
description: Verify a pushed branch, fix authorized failures, and prepare its PR for user review.
disable-model-invocation: true
---

# Prepare the current branch for review

Use this how-to guide after the intended changes are committed and pushed.
The user must authorize publication. Do not infer authority to merge.
During an implement run, use that skill's canonical publication, review, and monitoring gates instead of this duplicate workflow.

Do not include agent attribution in branch, commit, issue, or PR metadata.
Required Ground Control review records retain their narrow attribution exception.

## Phase 1: Create PR

1. Read `github_repo` from `.ground-control.yaml`.
2. Confirm the branch with `git branch --show-current`.
3. Check for its PR in that exact repository.
4. Create a PR against `dev` only if the authorized branch has no PR.
5. Use a Conventional Commit title and the repository's PR template.
6. Record the PR number, URL, and head revision.

Pass the repository explicitly to every GitHub command.
Use a body file for multiline PR text.

## Phase 2: CI Monitor

Find the workflows for the exact PR head revision.
Watch every applicable run to its terminal result.
A green run from an older revision does not verify the candidate.

For an authorized fix:

1. Read the failed step and bounded diagnostic evidence.
2. Fix its cause and run targeted regression checks.
3. Commit and push through the active workflow.
4. Watch the new revision's checks.

Keep full local suites out of this loop.

## Phase 3: SonarCloud Check

Read the project key and organization from `.ground-control.yaml`.
Use the existing SonarCloud monitor and the PR's exact revision.
Do not use a project key copied from another repository.
Fix actionable findings and repeat the CI watch after a push.
A deliberately unselected analysis is not a passing quality gate.
Record the configured selection evidence and follow the active workflow's decision boundary.

## Phase 4: Code Review

Keep the feature branch current with `dev` through a real merge.
Resolve conflicts without resetting, dropping commits, or force-pushing.
Use the installed review skill or the active implementation workflow's required review gate.
Fix real findings and verify the fixes with targeted checks.
Ask the user about significant architecture decisions or unexpected material scope expansion.

## Phase 5: Security Review

Require security review of the complete candidate at the exact PR head revision.
Give changed trust boundaries additional attention within that complete review.
Use the installed security-review capability or the active implementation workflow's required security-review gate.
Stop preparation if the required review capability is unavailable; report the missing capability and do not claim review completion.
Fix confirmed security findings and verify the protected behavior.
Preserve secret handling, private reporting, and repository publication boundaries.

## Phase 6: Final Commit & CI

After any fix, commit and push through the authorized workflow.
Verify the new head revision's CI and applicable SonarCloud result.
Refresh documentation and design evidence when the change affects them.

## Phase 7: Report (DO NOT MERGE)

Report the concrete outcome, checks, review fixes, remaining limits, and PR URL.
The user reviews and merges the feature PR.
Do not run `gh pr merge` or close the PR.
The separately invoked release skill retains its bounded release-script exception.
