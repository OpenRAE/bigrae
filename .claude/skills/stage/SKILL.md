---
name: stage
description: Stage selected files, run commit hooks, and fix failures.
disable-model-invocation: true
---

# Stage changes

Use this how-to guide for staged-file hygiene.
The implement skill owns staging and publication during an active implementation run.
Do not run a second staging workflow inside that run.

## Step 1: Identify Changed Files

1. Read `git status --short`.
2. Select the intended source and documentation changes.
3. Exclude credentials, secret files, local environment files, and unintended large binaries.

## Step 2: Stage Files

Stage the selected paths with `git add -- <paths>`.
Review `git diff --cached --stat` and the staged diff.

## Step 3: Pre-commit Loop

Run up to five iterations:

1. Run `pre-commit run` on the staged files.
2. Read any failure and fix its cause.
3. Stage files changed by fixes or hooks.
4. Repeat until the hooks pass.

Keep full suites and repository-wide checks in CI.
Do not use `pre-commit run --all-files` as the normal contribution loop.
After five failed iterations, report the exact unresolved failure and required decision.
Do not claim the hooks passed.

## Step 4: Report

Report the staged paths and hook result.
Do not commit or push without authority from the user or active implementation workflow.
