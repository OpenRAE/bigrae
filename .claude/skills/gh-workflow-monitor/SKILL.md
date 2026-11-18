---
name: gh-workflow-monitor
description: Monitor the current revision's GitHub workflows and report actionable failures.
disable-model-invocation: true
---

# GitHub workflow monitor

Use this how-to guide to inspect validation results.
Use the canonical `github_repo` in `.ground-control.yaml` for every `gh` operation.

1. Read the current branch and full head revision.
2. Find all workflow runs for that exact revision in the canonical repository.
3. Watch applicable runs with `gh run watch <run-id> --repo <owner>/<repo>`.
4. Read failed steps with `gh run view <run-id> --log-failed --repo <owner>/<repo>`.
5. Report the cause and proposed repair, or continue an already authorized repair workflow.
6. Report success only after all applicable runs for that revision pass.

Do not treat an older run or one successful workflow as proof for the complete candidate.
Keep raw sensitive logs out of public comments.
Do not deploy, publish, or merge through this monitoring task.
