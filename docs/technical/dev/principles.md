# Engineering Principles

This explanation describes the reasons behind BigRAE's engineering rules.
Use [local setup](local-setup.md) for development tasks and the [testing reference](../../dev/testing.md) for exact commands.
Accepted ADRs and current source determine the implemented controls.

## Core Philosophy

Keep solutions simple and explicit.
Reuse proven libraries and existing shared modules before adding custom code.
Report failures clearly instead of hiding them with a fallback.

## No Defaults Policy

Required configuration must fail when absent.
A default must not hide a deployment error.
This applies to environment variables, Terraform inputs, function parameters, and API contracts.

For example, these expressions have different meanings:

```python
# Hides a missing required value.
db_host = os.getenv("DB_HOST", "")

# Refuses a missing required value.
db_host = os.environ["DB_HOST"]
```

Explicit test, development, and build defaults exist at the configuration boundary.
`config._runtime_env.required_runtime_env` owns that distinction.
Those defaults do not authorize a production fallback.

## Git Discipline

### Branching

`dev` is the integration branch. `main` is the stable release line.
Feature branches start from `dev` and submit PRs to it.
Branch names do not trigger tenant deployments.
The [workflow guide](../../DEVELOPMENT_WORKFLOW.md) defines promotion and merge methods.

### Commits

Keep one logical change in each commit.
Describe what changed and why. Sign commits with GPG or SSH.
Do not include agent or vendor attribution in repository metadata.

### Pull Requests

Keep PRs focused. Explain the change, link its issue, and record verification evidence.
Resolve CI failures before requesting review.
The user or authorized maintainer decides whether to merge.

### Never

Do not force-push protected branches or commit directly to them.
Do not merge a feature PR without the required review and approval.
The release skill's bounded script is the exception described in the user's repository rules.

## Code Style

### Python

Ruff owns formatting and linting.
Use type hints where they improve contracts and docstrings for public functions.

### Terraform

Use `terraform fmt`, meaningful names, and reusable modules.
Keep each resource's responsibility clear.
Explain configuration whose purpose is not apparent from the code.

### General

Prefer readable code and functions with one responsibility.
Remove dead code instead of retaining commented implementations.

## Error Handling

Catch specific exceptions and report enough context to diagnose the failure.
Do not suppress errors to make a test pass.
Avoid bare `except:` clauses and vague user messages.
Stop an operation when it cannot continue safely.

## Testing

Business logic needs behavioral tests. Critical boundaries need integration coverage.
Use test doubles at real external boundaries, as ADR-019 requires.
Run targeted tests during development. Fast commit hooks handle hygiene; CI runs full suites and coverage gates.

## Security

Keep secrets out of code and logs. Validate untrusted input at its boundary.
Grant only the required authority and use secure transport.
Explicit local test fixtures do not authorize insecure production settings.

## Documentation

Choose the form that meets the reader's need: tutorial, how-to guide, reference, or explanation.
Keep one authoritative source and link related material.
Update guidance when behavior changes.
Preserve historical evidence with a clear applicability statement.
Use [CONTRIBUTING.md](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md#documentation) for the shared authoring workflow.

## Infrastructure as Code

### Terraform

Terraform defines the platform infrastructure.
Manual console changes require the documented bootstrap or recovery authority.
AWS state uses S3 and locking; GCP uses its configured backend.
Runtime range provisioning follows its owning adapter and lifecycle contract.

### Changes

Review a plan before apply. Change one environment at a time, from development toward production.
A successful plan does not authorize apply.

## Dependencies

Pin dependencies and review security updates regularly.
Minimize the dependency set. Prefer the standard library when it meets the need.

## Monitoring

Use structured JSON logs and correlation identifiers.
Alerts must identify an actionable condition.
Dashboards should expose the metrics needed for diagnosis and capacity decisions.

## When In Doubt

Resolve uncertainty from the owning source and accepted decisions first.
Ask the user about unresolved requirements or significant decisions.
Simplify the design and record information the next reader will need.
Use another review to challenge assumptions when the workflow requires it.
