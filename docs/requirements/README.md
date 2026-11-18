# Requirements reference

These files define the platform requirements and their traceability.
They specify obligations, not a list of delivered features.
Use the [current architecture](../technical/architecture.md) for the implemented ownership boundaries and support limits.

## Find a requirement

Each requirement has one file: `docs/requirements/<UID>/requirement.md`.
The frontmatter `id` must match its directory.
The `Statement` defines the obligation. The `Rationale` explains its purpose.
The `Traceability` section records related code, tests, documents, and issues.

| Prefix | Area |
| --- | --- |
| `CTF-` | Capture-the-flag platform |
| `PLAT-` | Platform, cloud, and portal infrastructure |
| `GEN-` | General requirements and shared concerns |

For example, [GEN-001](GEN-001/requirement.md) defines documentation coverage.
[GEN-002](GEN-002/requirement.md) defines executable architecture governance.

## Interpret status and evidence

`DRAFT` precedes implementation. `ACTIVE` means the requirement applies; it does not mean delivery is complete.
`ARCHIVED` and `DEPRECATED` retain the requirement record after its active use ends.
The file's frontmatter supplies its status.

An `IMPLEMENTS` link identifies code that implements part of an `ACTIVE` requirement.
A `TESTS` link identifies a test, not evidence that the test passed on a deployment.
A `DOCUMENTS` link can identify a missing capability or its tracking issue.
A `GITHUB_ISSUE` link identifies related issue work.
Read the linked source and the delivery evidence before making a support claim.

## Change a requirement

Requirement status and traceability change through reviewed pull requests.
Keep exact identifiers, link syntax, conditions, and obligations.
Do not weaken a statement to hide an implementation gap.
The [development workflow](../DEVELOPMENT_WORKFLOW.md) describes issue delivery.
The [contribution guidance](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md#documentation) describes documentation checks.
