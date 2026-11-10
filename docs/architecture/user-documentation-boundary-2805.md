# User documentation boundary (#2805)

Architecture guidance, inspected 2026-11-09 at revision
`5954ab13763deaba52a257d4ed8bde5bb1402ea6`.
Issue #2805 is the delivery contract; no formal requirement is attached.
This note applies existing decisions. It is not an implementation plan or proof of release support.

## Decision and reader boundary

Keep the existing page paths and single public MkDocs site under ADR-038.
Use the existing landing pages to route readers to Tutorials, How-to guides, Reference, and Explanation.
Directory names do not determine page purpose.
Do not add four directory trees, a new renderer, or a documentation taxonomy schema.

The reader route is installation guidance, first-range tutorial, then task guides.
Exact contracts and explanation must be reachable from that route without requiring architecture records.
Use `getting-started/concepts.md` and published technical pages for explanation where their content fits.
`docs/architecture/` is excluded from publication; it is not a user-help destination or a confidentiality boundary.

Reuse the [shared documentation tool boundary](documentation-tool-adoption-2804.md) and
[contributor instructions](../../CONTRIBUTING.md#documentation).
The #2804 delivery is present through merge `5954ab137` (PR #2854).
No new ADR, enforcement rule, exception, or tool is needed.

## Release evidence gap

On 2026-11-09, the [latest-release API](https://api.github.com/repos/OpenRAE/bigrae/releases/latest)
returned [v4.1.1](https://github.com/OpenRAE/bigrae/releases/tag/v4.1.1).
Its source revision is `c04d53db89c522d7437f3f0b508379bb96eaa58b`.
That tree lacks `.github/workflows/release-gcp.yml`, `platform/deployer/gcp/`,
`shifter/installation/gcp_release.py`, and `scripts/bootstrap/gcp_install.py`.
The current install page itself excludes v4.1.1 and earlier from deployer availability.
Thus, the current published-container route has no substantiated eligible release in this preflight.
Release metadata alone also cannot establish whether registry images exist or pass provenance checks.

Do not describe the current install route as verified for the latest release.
The delivery evidence needs an eligible published revision, exact artifacts, provenance, and applicable backend evidence.
If unavailable, state that limit explicitly; do not substitute a development build or start a release.
GCP source support, AWS source support, backend admission, published artifacts, and live qualification are separate facts.
Neither backend registration nor a planned adapter establishes a supported release.

ADR-068 parks the model broker even when retained screens or settings exist.
Describe independently supported model-source administration separately from that unavailable runtime.

## Ownership of mixed content

Paths below are relative to `docs/`, except `README.md`.
The delivery PR records actual mixed sections, linked destinations, and their owning issue.
This table defines the boundary; it does not require page moves or duplicate pages.

| Content | Boundary |
| --- | --- |
| `README.md`, `index.md`, section indexes | #2805 owns reader routes and accurate support statements. Preserve the separate contributor route to `technical/dev/setup.md`. |
| `getting-started/install-gcp.md`, `deploy-with-agent.md` | #2805 owns these entry paths. Coordinate procedural content with #2806, which owns deployment and recovery guidance. Link one agreed installation procedure; do not maintain competing command sequences. |
| `getting-started/quickstart.md` | #2805 owns a bounded learning exercise. Link operator-owned installation and failure recovery; range cleanup is distinct from installation teardown. |
| `features/`, `scenarios/`, `reference/faq.md`, user tasks in `how-to/` | #2805 owns user tasks and discovery. Separate exact fields and limitations only where mixed content obstructs the task. Link the #2807 reference owner. |
| Deployment configuration, privileged image preparation, migration, retention, disaster recovery | #2806 owns the operator procedures, including relevant mixed sections in `how-to/`. A directory name does not transfer ownership. |
| Wire/configuration contracts, pack authoring, runtime capability definitions | #2807 owns exact reference and authoring guidance. Link real published destinations; coordinate any destination edits. |

Reuse the #2761 delivery at `5f9d5db3cecbac5b748b54eb2a52fa4eba971b90`.
It already supplies the install, agent-delegation, first-range, and entry pages.

[Issue #403](https://github.com/OpenRAE/bigrae/issues/403) remains open at inspection.
It requests catalog list/detail guidance, realizability, administrator pack upload, and index links.
Reconcile it against `ScenarioListPage.tsx`, `ScenarioDetailPage.tsx`, and `PackUploadForm.tsx` under `frontend/src/features/`.
Coordinate user upload tasks with #2807 authoring reference and #2806 preparation instructions.
Do not silently close either issue or treat a historical PR numbered 403 as its delivery evidence.

## Canonical contracts and cross-cutting layers

Application paths in this table are relative to `shifter/shifter_platform/`.
Examples describe supported interfaces; they do not create alternative validators or permission rules.
`config/api_urls.py` mounts the native account-administration composition before retained legacy routes.
Check the mounted handler; an old view, staff flag, or role table alone does not establish current authority.

| Layer and canonical incumbent | Required treatment |
| --- | --- |
| Browser routes and API shapes: `frontend/src/app/nav.ts`, `frontend/src/router.tsx`, `frontend/src/features/mission-control/routes.ts`, `mission_control/api/serializers.py`, `openapi/v1.json` | Verify labels, available actions, deep links, DTO fields, and defaults against the selected revision. The generated client contract is `frontend/src/api/schema.d.ts`; do not introduce another API schema or edit generated files. |
| Authentication and authorization: `shared/api/permissions.py`, `shared/credentials.py`, `shared/authorization/`, `mission_control/api/permissions.py`, `cms/services/_scoped_range_launch.py` | Keep login, credential ceilings, current policy, customer scope, range ownership, event authority, and cloud IAM distinct. State the permission for each task. UI visibility and an administrator label do not establish backend authority. Browser mutations retain same-origin sessions and CSRF through `frontend/src/api/client.ts`. |
| Input validation: `shared/api/closed_serializer.py`, `shared/api/strict_json.py`, `mission_control/api/serializers.py`, `cms/assets/validation.py`, `shared/uploads/inspection.py`, `cms/services/_scoped_uploads.py` | Preserve exact accepted shapes and upload admission. Extension, header inspection, size, quota reservation, and finalization are separate checks. Do not suggest renamed files, dummy uploads, or direct storage writes to bypass them. |
| Catalog and runtime admission: `cms/scenarios/inbox_packs/manifest.yaml`, `cms/services/_inbox_catalog.py`, `config/management/commands/initialize_installation_catalog.py`, `cms/services/_range_backend_admission.py`, `shared/range_instantiation_policy.py`, `shared/raes/` | Verify installed catalog, identity activation, content authorization, pinned RAES contracts, and selected backend capability. Pack upload does not authorize executable adapters. Reuse isolated worker and administrator binding boundaries. No private pack content or identity-based core behavior belongs in this rewrite. |
| Configuration and environment: repository `shifter/installation/{loader,schema,settings_gcp,settings_aws,gcp_release}.py`, backend bundles and published contracts; application `config/env-manifest.json`, `config/_runtime_env.py` | Root parsing rejects duplicate/merge keys. Backend models reject unknown settings and validate secret references. Examples must satisfy those existing shapes at their cited revision. Runtime environment binding and deployment input are different contracts. No new configuration keys, schema, or environment variable is required for prose. |
| Secrets and host exposure: `shared/cloud/sensitive_env.py`, installation secret-reference checks, `gcp_catalog.py` under `shifter/installation/`, `.pre-commit-config.yaml`, ADR-004 | Use synthetic public values and existing secret stores or private credential files. Keep values out of process arguments, URLs, shell history, tracing, screenshots, CI output, and PR evidence. Preserve credential-file modes and scoped container mounts. Do not collect secret-file contents or copy raw operator logs into public records. |
| Errors and observability: `shared/api/errors.py`, `shared/errors.py`, `shared/log_sanitize.py`, `shared/audit/`, `frontend/src/api/errors.ts`, installation `errors.py` | Preserve the existing API envelope and authored error codes/messages. Troubleshooting uses safe request identifiers and existing audit evidence. Do not request raw exceptions, provider responses, bearer proofs, or unredacted terminal exports. Preserve CLI exit distinctions and native checker failures. No new exception family, logging schema, telemetry service, or evidence store. |
| Persistence and lifecycle: `cms/services/_range_destroy_transition.py`, Engine services, `shared/enums.py`, `shared/schemas/range.py` | CMS owns desired lifecycle; Engine owns realized state and operation results. Accepted launch/cancel/destroy is not completed work. Confirm terminal cleanup of the exercise's exact range. Do not delete SQL rows, Terraform state, or locks to make a failed operation appear complete. |
| Prose quality and supply chain: `CONTRIBUTING.md`, `tools/install-vale.sh`, `.vale.ini`, Makefile docs targets, `.ste-required.txt`, `.github/workflows/vale.yml` | Reuse verified doc-tools v0.1.0 and Vale with explicit changed paths. Keep remote analysis and dictionary processing disabled. Add fully rewritten pages to the existing required list; do not invent an inventory, style guide, baseline, analyzer, or custom skill. Review purpose and full STE meaning separately from the three automated checks. |
| Publication, coverage, and workflow: `mkdocs.yml`, `docs/requirements.txt`, `.github/workflows/docs.yml`, `.github/quality-path-filters.yaml`, `scripts/quality_ownership/`, `docs/adr/documentation-coverage.yaml`, `scripts/adr_guard/` | Preserve the single build, publication exclusions, read-only PR jobs, and separate Pages deployment permissions. Coverage checks require public index-reachable targets; retain source-to-handbook associations. Guardrail changes follow ADR-002. Use `.ground-control.yaml` repository identity and existing PR evidence conventions; no requirement record is needed. |

## Tutorial and verification limits

The tutorial needs a known installed release, active authorized principal, selected workspace, available public synthetic pack, and applicable backend prerequisites.
Use the release's catalog contract rather than an assumed legacy scenario inventory.
Current `RangeLaunchPage.tsx` permits an explicit no-agent scenario and presents workspace selection.
The current quickstart requires an upload unconditionally and omits workspace selection.
Correct that difference only against the chosen supported revision.
Never require a dummy installer to satisfy obsolete instructions.

Use harmless guest observations, visible expected results, and confirmed range cleanup.
Stop at permission, capability, provenance, or admission failures and link the owning recovery guide.
Do not recommend unconditional cancel/relaunch after a timer or promise fixed provisioning times without evidence.
Agent installers, personal API credentials, deployment credentials, model sources, and executable adapters are different resources.
Likewise, CTF participation, Mission Control use, authoring, application administration, and cloud operation are different authorities.

Source inspection is not test execution; contract tests are not live acceptance.
Existing focused test locations include `RangeLaunchPage.test.tsx`, catalog and pack-upload component tests,
`tests/cms/test_inbox_bootstrap.py`, `tests/cms/services/test_principal_uploads.py`,
`tests/cms/test_services_range_destroy_cancel.py`, `shifter/installation/tests/test_gcp_release.py`,
and `scripts/bootstrap/tests/test_gcp_product_install.py`.
The last two paths are relative to the repository root.
Use existing targeted tests when needed; do not add tests that assert rewritten sentences.
No runtime behavior changes here require mutation testing.

`mkdocs.yml` currently generates navigation from the tree; it has no explicit `nav` list or redirect plugin.
Several missing-link and anchor checks have severity `info`.
Thus, `make docs-build` passing does not establish correct reader routes, anchors, or redirects.

Inspect the rendered changed routes, root README links, headings, search results, and useful inbound heading links.
Keep old URLs; ADR-038-R3 requires any necessary relocation to remain verbatim and separate from rewriting.
Check keyboard navigation, descriptive links, diagram alternatives, and meaning without color under ADR-055.
Do not infer Mermaid rendering or accessibility from a successful Markdown parse.

The delivery PR records source paths, source revisions, checks, results, corrected differences, and unverified behavior.
Preserve legal text, notices, quotations, generated records, and exact evidence through narrow explained exclusions.
Edit maintained generator prose at its source.
Local writing checks use explicit changed paths; full corpus checks remain in CI.
Architecture work also requires `python3 scripts/adr_guard/adr_guard.py --all --level ci`.

## Extension seam and non-goals

The next release or backend belongs in its existing release/catalog/capability contract and linked reference.
Guides select a release revision, backend, workspace, and installed catalog entry through those existing interfaces.
Do not copy a static support matrix into every tutorial or branch on scenario identity.
The existing required-path list admits the next rewritten page without new CI selection logic.

This preflight does not rewrite guides or change product behavior, application schemas, persistence, authentication, or deployment configuration.
It adds no implementation plan, runtime abstraction, tool, skill, dictionary copy, hosting, or external text processing.
It authorizes no release, cloud provisioning, live exercise, publication, issue closure, or merge.
