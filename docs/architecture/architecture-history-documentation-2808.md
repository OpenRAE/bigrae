# Architecture and historical documentation boundary (#2808)

Design guidance, 2026-11-09. Diataxis purpose: explanation.
Inspected revision: `5954ab13763deaba52a257d4ed8bde5bb1402ea6`.

Issue #2808 is the delivery contract. No formal requirement is attached.
The prerequisite #2804 merged through PR #2854 at this revision.
This note records design boundaries. It is not an implementation plan or delivery evidence.

## Authority and reader purpose

Apply the [shared documentation boundary](documentation-tool-adoption-2804.md)
and [contributor guidance](../../CONTRIBUTING.md#documentation).
Existing ADR-002, ADR-004, ADR-019, ADR-022, ADR-038, ADR-055, and ADR-069 cover this work.
No new ADR, schema, validator, or exception is needed.

Keep reader purpose, decision status, and implementation evidence separate.
An explanation can describe a proposal. An accepted decision does not prove delivery.
An `ACTIVE` requirement does not prove implementation. A passing source test does not prove deployment or live qualification.

The [architecture index](index.md) already distinguishes historical preflights from accepted decisions and durable designs.
Preserve that distinction at direct document links, not only at landing pages.
Follow amendments and supersession links before describing a decision as current.

Preserve obligations, conditions, quantities, identifiers, commands, quotations, and exact evidence.
Do not change normative meaning to satisfy a writing check.
Preserve legal text, third-party notices, and generated records. Edit maintained generator prose at its source.

These dispositions define the review boundary, not a completed migration inventory.
Each family needs its maintained or preserved status, purpose, source revision, and exclusion reason in the delivery PR.
Mixed families need narrower entries for their different records.

| Family | Reader purpose and treatment | Source boundary |
| --- | --- | --- |
| `docs/technical/architecture.md` | Maintained explanation of current ownership, runtime, and support. Link operating tasks to task guidance. | Current source owners, architecture rules, deployment configuration, and relevant targeted tests. Record the reviewed revision. |
| `docs/architecture/` | Mixed explanation and reference. Maintain introductions and durable designs; preserve dated preflights and reviews with applicability notes. | Follow accepted ADRs and supersession. Verify historical claims at their recorded revision, not against current code alone. |
| `docs/adr/` | Decision rationale is explanation. Exact rules, contracts, registries, and exceptions are reference. | Preserve IDs, status, rule strength, typed contracts, evidence, and amendment links. Do not silently reopen an accepted decision. |
| `docs/requirements/` | Reference for normative statements and traceability; maintain reader guidance. | Preserve frontmatter keys, values, lifecycle, and link syntax. A prose rewrite does not activate, retire, or deliver a requirement. |
| `docs/audit/` | Reference for dated findings and evidence. Maintain introductions and current applicability notes. | Preserve original findings and outputs. The March audit names a worktree and date, without an exact source revision. |
| `docs/design/` | Maintain explanation and reference according to each design's status. Separate active operating tasks when useful. | Verify current claims against actual consumers. Preserve proposed and historical scope, executable examples, and source-bound evidence. |
| `docs/research/` | Reference for research results; explanation for repository-owned interpretation. | Preserve dates, citations, samples, estimates, uncertainty, and quotations. Code cannot validate an external research result. |
| `docs/ctf/` | Research reference and explanation, according to the document. | Distinguish recommendations and estimates from implemented scoring or scheduling behavior. Retain the original evidence limits. |
| `docs/technical/notes/` | Mixed historical evidence and maintained guidance, including prompts and image context. | Inspect ownership and use; neither a hidden path nor an image extension proves exclusion. Preserve source-bound screenshots without repeating private content. |
| `docs/technical/plans/` | Proposed or historical material until verified. Active operating instructions belong in linked task guidance. | Preserve dates and original intent. A checklist or plan does not establish shipped behavior. |
| `docs/_deprecated/` | Preserved historical reference with maintained routing and status notes. | Retain original facts and evidence. Link current replacements without rewriting history to match today's code. |

## Canonical owners and validation boundaries

| Layer | Existing owner and required boundary |
| --- | --- |
| Architecture and domain ownership | Use `docs/adr/index.yaml`, `.importlinter`, and `scripts/check_layer_imports/layer_imports.yaml` together. Check actual owning services, shared contracts, and deployment configuration. Do not infer ownership from directory names or old diagrams. |
| Machine-read records | `scripts/adr_guard/_guard/checks/adr_registry.py` and its contract helpers own registry validation. The `.yaml` registries use JSON syntax. Preserve their shapes, typed fields, rule IDs, and evidence paths. Ground Control requirement files remain the requirement record; do not create a parallel status database. |
| Examples and schemas | Tests consume `docs/architecture/model-access/example-policy.*.json` and the canonicalization and allocation vectors. Preserve those contracts. Their descriptions need review, but their data is not free prose. Published schemas stay with their existing generators and validators. |
| Coverage and drift | `docs/adr/documentation-coverage.yaml` and `_documentation_drift.py` own feature discoverability and source-to-handbook pairing. Preserve their schema, base comparisons, and index links. This manifest is not the historical-document inventory or rewrite completion list. |
| Writing configuration | Reuse `.vale.ini`, `tools/install-vale.sh`, and doc-tools v0.1.0 through the existing Makefile targets. Its `.ste.yml` owns the three selected STE checks. Keep dictionary and remote analyzer features disabled. Human review still establishes meaning and Diataxis purpose. |
| Authentication and workflow policy | `.github/workflows/vale.yml` and `docs.yml` keep PR checks under `contents: read`. Preserve action pins, credential-free prose checks, separate Pages permissions, and existing publication conditions. No application or cloud identity is needed. |
| Privacy and secret handling | Retain gitleaks, private-key checks, and ADR guard identifier checks. Site exclusion is not confidentiality. Neither checks nor preserved evidence authorize repetition of private identities in prose, screenshots, diagrams, diffs, PR evidence, or logs. Use synthetic examples and keep private evidence with its owner. |
| Host and shell inputs | Use explicit, quoted repository-relative paths, including filenames with spaces. Existing Makefile selection uses NUL-delimited Git output. Failed selection must fail; an empty selection must not trigger a corpus scan. Do not execute historical commands to verify their wording. No tokens in process arguments or credential tracing. |
| Errors and records | Preserve native tool findings and nonzero exits. Separate findings from setup or configuration failure using existing reporting modes. CI corpus reports retain native summaries to avoid repeating evidence. Git history and PR verification records suffice; no new error hierarchy, telemetry, report schema, or audit store. |
| Quality routing | `.github/quality-path-filters.yaml` and `scripts/quality_ownership/` own fail-closed classification. Reuse ADR guard's workflow model for workflow structure. Rule changes need matching ADR enforcement documentation; waivers belong in `docs/adr/exceptions.yaml` with owner and expiry. |
| Rendering and access | `mkdocs.yml`, `docs/requirements.txt`, and `docs.yml` own the single public site. Keep all exclusion rules, including the architecture inventory exception. Preserve URLs and useful heading anchors. Check rendered headings, descriptive links, diagram alternatives, and keyboard access after navigation changes. Use ADR-055's existing accessibility tools where applicable. |

Application authentication, serializers, controllers, services, repositories, and database persistence are source evidence, not extension points for this work.
Runtime environment bindings remain owned by `config/_runtime_env.py`, `_env_manifest.py`, and `env-manifest.json` under `shifter/shifter_platform/`.
Do not add contributor-tool settings there.
Runtime exceptions, safe API errors, logging, and audit remain with `shared/exceptions.py`, `shared/errors.py`, `shared/api/errors.py`, `config/_logging_config.py`, and `shared/audit/`.
Do not change an API error envelope or import application code to process documentation.

## Evidence, rendering, and extension seams

For current claims, record source paths, revision, selected checks, results, and corrected differences in the delivery PR.
Use the owning subsystem's existing tests when a behavioral claim needs verification.
State when behavior is absent or unverified. A test's existence is not a passing result.

For historical claims, use the recorded revision and retain original outputs.
A document's commit date does not establish the source revision it assessed.
If the recorded revision or dirty worktree is unavailable, state that the evidence cannot be reproduced.
Add a separate status note rather than replace the original finding.

Representative routes already exist:

- [Current architecture](../technical/architecture.md) and the [architecture index](index.md).
- [Accepted ADR-070](../adr/070-github-less-gcp-deployment.md).
- [Superseded ADR-059](../adr/059-range-model-access-broker.md), which links to [ADR-068](../adr/068-model-access-broker-parked.md).
- [Requirement GEN-001](../requirements/GEN-001/requirement.md).
- [Dated timing research](../research/ctf-timing-completion-research.md).
- [REV1 review](rev1/README.md), which records its baseline, and the [March audit](../audit/2026-03-23-ctf-audit/README.md), which does not.

These are route samples, not proof that their full content is current or rewritten.
Check routes in both repository and published contexts where applicable.
MkDocs reports several link and anchor failures as informational; `--strict` alone cannot prove route integrity.
An off-site target must not appear to be a reachable site page through a broken relative link.
ADR-038-R3 requires verbatim relocation. Prefer existing paths; keep any required move distinct from prose editing and verify published redirects.

Some coverage entries point to excluded architecture pages.
Passing coverage does not establish publication or route integrity; do not change exclusions to make those links appear valid.
The inspected `frontend/e2e/a11y/matrix.ts` and `axe.spec.ts` cover SPA routes.
They do not establish site or design-system accessibility. Record the actual rendered checks and manual keyboard results.

The design-system [README](../design/design-system/README.md) and HTML explanations are maintained prose, including claims about consumers and accessibility.
HTML, CSS, JavaScript, Mermaid syntax, JSON values, and frontmatter also carry executable or machine-read meaning.
Markdown checks do not establish coverage for those contents.
Review their maintained descriptions and diagram labels without changing selectors, tokens, contracts, or literal evidence for style.

Check actual consumers before repeating the README's claim that product surfaces consume its foundation assets.
The inspected source search did not establish that claim.
Preserve diagram sources and add accurate text alternatives without exposing private evidence.
Avoid a new HTML extractor, checker, dictionary pipeline, or diagram renderer.

Use the existing `.ste-required.txt` path list as the rewrite completion seam.
Enroll fully rewritten Markdown pages after explicit-path Vale and STE checks pass.
Document narrow evidence exclusions beside supported directives and in the PR; keep maintained introductions checked.
Keep family disposition and source evidence in the PR, not a new manifest or frontmatter schema.
Future feature-boundary associations extend existing `drift_sources`; new accessibility surfaces extend ADR-055's existing surface matrix.
Tool upgrades remain at the existing version and checksum boundary.

## Non-goals and verification limits

This design note alone does not implement #2808, rewrite the corpus, or establish STE or accessibility conformance.
The implementation changes documentation, not runtime behavior, requirement delivery, accepted policy, executable examples, or publication scope.
Do not add services, hosting, external text processing, custom tools, or skills without the required user permission.
Do not create prose-string tests, parallel validators, broad exclusions, new baselines, or corpus checks in pre-commit.

Use targeted local checks; CI owns full checks and corpus reports.
Run the required full ADR guard for architecture changes.
Use relevant structural checks when machine records change, and `actionlint` if workflows change.
Neither registry validity nor a successful build establishes factual accuracy, decision authority, or live qualification.
