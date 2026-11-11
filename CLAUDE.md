# Repository agent guidance

Use this reference with [AGENTS.md](AGENTS.md), the repository's current agent rules.
Read the task and existing source before changing files.
Follow the user's request and preserve its scope.

## Guiding Principles

- Keep the solution simple. Reuse proven tools and existing patterns.
- Answer the question or perform the requested action.
- Treat errors, failed tests, and material quality problems as work to resolve.
- Research sound architecture before implementation.
- Do not repeat an incorrect pattern only for consistency.

## How To Work

1. Read the related source, designs, and current repository rules.
2. Check whether the requested behavior already exists.
3. Resolve uncertainty from those sources where possible.
4. Ask the user about unresolved requirements or significant architecture decisions.
5. Implement authorized work without speculative features or unbuilt-feature documentation.
6. Run targeted checks. Keep full suites in CI.
7. Report the result, evidence, and material limits plainly.

For prose, use the shared documentation skill and explicit-path checks in [CONTRIBUTING.md](CONTRIBUTING.md#documentation).
Review a file's purpose, name, duplication, and consumers before changing it.
Get permission before work beyond the user's request.

## AWS

Deployment configuration selects the cloud and region.
Use the selected deployment's values; do not infer them from an old example.
The retained AWS development examples commonly use `us-east-2`.

## Platform Elements

The [current handbook](docs/technical/architecture.md) describes the four platform domains and their service boundaries.
Use it with the owning source and accepted ADRs.
Do not treat historical notes as current implementation.

## Lessons Learned

Read the active conversation after context compaction.
Use fixtures and tests at real boundaries instead of many small tests with repeated inline mocks.
The test estate has a documented history of memory exhaustion with excessive mocks and workers.

Keep responses concise and technical. Do not add marketing language.
Verify URLs and prefer official technical documentation.
Do not invent requirements or add unsolicited features.

**Git operations:** the Ground Control implement skill owns issue-driven commit, push, PR, CI, and review work.
Outside that authorized workflow, do not commit, push, or open PRs without explicit user direction.
The user reviews and approves feature-PR merges and merges into `main`.
The user's standing rules permit merging `dev` into a feature branch and resolving its conflicts.
When the user invokes the release skill, use its release script and its bounded merge checks.
Do not infer release authority from an implementation task.
