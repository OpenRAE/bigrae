# Blocking Trivy configuration scan: architecture preflight (#2566)

Status: pre-implementation guidance. Date: 2026-11-24.

Issue #2566 is the contract; no formal requirement is attached.
Source baseline: `3b30e45f2e589fa3706940beeeaf8092559b8751`.
This explanation records constraints and unresolved decisions, not an implementation plan.
No infrastructure, scanner policy, or risk acceptance changes in this preflight.
No fresh scan with the CI-pinned binary was obtained; finding counts remain unverified.

An additional Terraform-only diagnostic used installed Trivy 0.75.0 with cached checks.
It is not the CI 0.71.2 verdict; observations below retain that version limit.

The [#2558 preflight](blocking-config-security-preflight-2558.md) supplies the broader security boundaries.
Its [implementation design](blocking-config-security-design-2558.md) deferred this scan.
Existing ADR-003, ADR-004, ADR-008, ADR-017, ADR-020, ADR-037, and ADR-070 cover the work.
No new service, schema family, scanner framework, or exception hierarchy is needed.

## Current-source corrections and finding boundaries

Paths in this table are relative to `platform/terraform/`.
An owning issue is a delivery dependency, not permission to suppress an unresolved finding.
Completion requires current scan evidence for every disposition, including findings absent from the issue's historical inventory.
Reports can repeat through environment compositions; preserve the defining resource and caller when reconciling counts.

| Rule | Current owner and constraint |
| --- | --- |
| GCP-0007 | `gcp/modules/image-export-storage/main.tf` replaces removed `packer-build-infra`. Object-admin, legacy-reader, and scratch-admin grants already use bucket IAM resources. Preserve the separate metadata-only project discovery role. Verify the exact reported grant before changing permissions; resource scope alone does not prove the role is minimal. |
| GCP-0066 | ADR-008-R5 and the [#2564 design](gcp-gcs-cmek-design-2564.md) already govern GCS CMEK. Reuse `gcp/modules/gcs-cmek`, the bucket-owner modules, and `scripts/bootstrap/gcp_storage_cmek.py`. Do not repeat that migration or change native lease-state encryption. Current source is not a fresh scan or live-readback verdict. |
| AWS-0132 | `modules/log-aggregation/s3.tf` already gives central logs a customer-managed key. The separate ALB log bucket deliberately uses SSE-S3. Establish the actual resource and scanner interpretation. The current #2564 design explicitly excludes AWS S3 CMEK, despite #2566 assigning it there; reconcile ownership before claiming dependency completion. |
| AWS-0104 | #2563 owns egress narrowing. Management egress and NGFW dataplane forwarding have different purposes. ADR-020 requires actual routing and firewall containment; it does not justify unrestricted dev-box or runner egress. |
| AWS-0090 | `modules/portal/s3` and `modules/log-aggregation` disable versioning. `modules/engine-state` already enables it and manages noncurrent versions. Versioning changes retention and deletion semantics. |
| AWS-0089 | Source buckets need S3 request logging, distinct from application, Firehose, and ALB logs. No existing `aws_s3_bucket_logging` resource was found. A terminal destination needs a narrow, documented no-self-logging policy; adding sinks indefinitely is not a solution. |
| AWS-0177 | `modules/portal/rds` already takes `deletion_protection` and `skip_final_snapshot`. Dev passes false/true; prod passes true/false. Use those inputs and the existing teardown boundary, rather than hardcoding the module. Check every reported database, including any separate Guacamole resource. |
| GCP-0014 | `gcp/modules/portal/cloud-sql/main.tf` lacks `log_temp_files`. Its metadata logging differs from the SQL-text exclusions in #2084. Preserve that confidentiality decision and verify effective logging behavior. |
| AWS-0342 | Inspect each PassRole statement's resource namespace, service condition, target trust, and permissions boundary. Existing grants include service-filtered roles and a narrowly named RDS-monitoring grant without `iam:PassedToService`. A CKV_AWS_355 wildcard rationale is not proof about every PassRole grant. |
| GCP-0033 | The runner disk's existing CKV_GCP_38 decision chooses Google-managed encryption. CSEK, CMEK, and Google-managed encryption are separate controls. Any matching Trivy exception must name this disk and its actual mode. |
| GCP-0074 | The supplemental diagnostic points to `range_deny_ingress_all`'s `deny { protocol = "all" }`, not an allow rule. Source confirms that default-deny block. Narrowing it would weaken containment. Confirm the pinned scanner's cause before recording an exception; ADR-017/ADR-020 are not a blanket GCP firewall waiver. |

The export identity must retain build/export/read/cleanup permissions on its owning buckets without acquiring evidence overwrite or deletion rights.
The existing create-only evidence grants in `gcp/modules/cicd-oidc-identity` remain separate.
Do not replace a flagged predefined role with equivalent broad custom permissions merely to hide its name.

## Storage, logging, and lifecycle decisions

**Keep delivery protocols separate.** AWS documents SSE-S3 as the supported encryption for both
[ALB log delivery](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html)
and direct [S3 server access log delivery](https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html).
Thus the existing SSE-KMS Firehose archive cannot automatically become the S3 request-log destination.
A provider-supported SSE-S3 destination can require a resource-specific CMEK-policy exception.
This is a service constraint, not evidence that CMEK is configured or an automatic new risk acceptance.
The supplemental AWS-0132 diagnostic points to the ALB bucket's SSE-S3 encryption block in both environment compositions.

The S3 destination must belong to the source account and Region.
It must not enable Object Lock/default retention, Requester Pays, or recursive server access logging.
Use bucket-owner-enforced ownership and bucket policy delivery permissions, not legacy ACL grants.

The S3 principal is `logging.s3.amazonaws.com`; it differs from the existing ALB and Firehose principals.
Scope `s3:PutObject` to source-specific prefixes with source-account and source-ARN conditions.
Retain public-access blocks and TLS enforcement; check explicit denies against real service delivery.
Policies must be ready before source logging is enabled.

Reuse `modules/log-aggregation` policy documents, retention inputs, and policy-readiness output conventions where applicable.
The existing optional ALB bucket is not an unconditional logging dependency.
Logging must work when ALB logging or application log aggregation is disabled.
Range owns `engine-state`; portal already reads range state.
Do not make range depend on a portal-owned sink and create a state dependency cycle.
Keep sink ownership within the appropriate existing root and account/Region boundary.

**Bound retained versions deliberately.** AWS documents that an ordinary delete adds a
[delete marker](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectVersions.html); old versions remain.
`shared/cloud/aws/storage.py` and `ctf/s3.py` currently delete without a version ID.
Enabling upload versioning therefore changes the existing ephemeral-data decision and physical erasure timing.
Define the permitted noncurrent retention and expired-marker cleanup within the owning bucket lifecycle.

Log expiration must also remove noncurrent versions within the intended retention policy.
Reuse the `engine-state` lifecycle pattern without copying its recovery window onto uploads or logs.
Keep one lifecycle configuration per bucket, state recovery, KMS availability, and existing resource addresses.
Do not introduce blanket version-purge permissions, `force_destroy`, or bucket replacement to simplify cleanup.
For any AWS key change, distinguish a new default from encryption of existing versions; keep migration within the key owner's delivery boundary.

The existing S3 exceptions still describe disabled versioning and deferred logging.
Reconcile only the remediated clauses and annotations; retain independently justified replication/notification decisions.
Application log storage is not automatically a terminal S3 access-log sink.
S3 access logs can contain object identifiers and request metadata; restrict readers and retention accordingly.
Delivery is best effort, so this control is not a complete application audit ledger.

**Preserve database confidentiality and intentional teardown.**
[GCP-0014](https://avd.aquasec.com/misconfig/google/sql/avd-gcp-0014/) calls for `log_temp_files = "0"`.
[PostgreSQL logging](https://www.postgresql.org/docs/16/runtime-config-logging.html) distinguishes temporary-file metadata from statement and error-statement logging.
Do not enable SQL-text logging to satisfy this rule.
Verify effective flag defaults, role overrides, pgaudit settings, and emitted spill/error logs with synthetic data.
An omitted statement flag does not prove SQL text is absent.

Check provider support and restart impact without changing the database major version.

For RDS, protected normal operation can use the existing environment input.
`scripts/bootstrap/aws_env_destroy.py` already lifts protection through scoped, ownership-checked Terraform overrides.
Preserve that deliberate teardown path and snapshot decision; deletion protection is not backup or `prevent_destroy`.
Retaining unprotected dev operation needs an explicit, factual policy disposition, not a false-positive label.

## Blocking workflow and exception contracts

The canonical scan remains in `.github/workflows/_quality.yml` on a credential-free hosted runner with `contents: read`.
Keep its checksum-verified Trivy 0.71.2 download, pinned actions, target roots, severities, and existing temporary-directory exclusion.
The targets are `shifter/engine`, `shifter/shifter_platform`, `shifter/packer`, and `platform/terraform/`.
Preserve Dockerfile scanning as well as Terraform scanning.
Record the checks-bundle identity with scan evidence; the executable pin alone does not freeze rule content.

Reuse the neighboring OSV job's status aggregation and failure-time artifact upload.
Every target must run even after a finding or scanner error; the final status must fail on either.
A bare `--exit-code 1` under `set -e` exits early and loses later results.
The current Trivy upload step lacks `if: always()`; flipping the scan alone would skip failure diagnostics.
Keep distinct per-target SARIF files, missing-artifact errors, and the existing 14-day retention.

A SARIF file alone does not prove every target parsed and evaluated successfully.
Do not treat skipped files, parse/evaluation failures, or missing expected resources as clean scans.
The supplemental scan warns about missing root inputs; use synthetic inputs and native contracts to verify conditional behavior without exposing operator tfvars.

Reuse these policy owners together:

- `quality_ownership.py` owns blocking-job classification; remove Trivy's advisory classification.
- `_deploy_workflow_plan_scope.py` owns security-job immunity to `skip_tests`; include the actual Trivy job identifier.
- `.github/quality-path-filters.yaml` and `scripts/quality_ownership/contract.py` own routing and responsibility shapes.
- `_workflow_model.py` owns safe workflow loading and expression evaluation; reuse it in workflow tests.
- ADR-004-R11 and `docs/technical/dev/adr-enforcement.md` own the documented scanner posture.

Keep the stable job ID unless a rename is necessary; remove misleading display text either way.
Reconcile check consumers if identifiers change.
Blocking classification does not require assigning Trivy a new path-ownership responsibility.
An always-running job added to that contract fails its docs-only negative routing invariant unless routing is reconciled.
Do not change the canonical routing schema or duplicate its parser to accommodate this job.

Use exact-resource [Trivy inline ignores](https://trivy.dev/docs/v0.71/guide/scanner/misconfiguration/config/config/#filtering-resources-by-inline-comments)
only after verifying the actual rule and rationale.
Pair each with the existing JSON-compatible `docs/adr/exceptions.yaml` schema: `rule_id`, `owner`, `reason`, `expires_on`, and affected `paths`.
Use ADR-004-R11, include the scanner rule ID, and align native ignore expiry with registry expiry.
`scripts/adr_guard/_guard/_common.py` already validates registry shape and expiry; add no second exception registry.
Checkov annotations do not suppress Trivy, and registry metadata alone does not suppress either scanner.

Do not use wildcard ignores or module-wide suppression to cover a resource-specific decision.
An ignore on an IAM policy resource also covers its statements; regression checks must prevent a future unfiltered PassRole grant.
The root `.trivyignore.yaml` and deployer ignore file govern image vulnerabilities; keep configuration exceptions separate.
This preflight authorizes no new exception or acceptance of unfinished dependency work.

## Cross-cutting layers and extension seams

| Layer | Canonical incumbent and pass condition |
| --- | --- |
| Identity and authorization | Existing bucket IAM/policies, purpose identities, OIDC conditions, AWS permissions boundaries, and target-role trust. No cloud credentials or additional token scopes enter configuration scanning. Reuse `check_tf_iam_role_naming` and `check_tf_gcp_iam_resource_scope`. Changes to `global/iam` retain its out-of-band apply/drift boundary. |
| Configuration and policy shapes | Terraform variable types, validation/preconditions, locked providers, and `platform/terraform/validation-inventory.yaml` through `scripts/check_tf_roots`. Keep infrastructure sink references in module inputs. Only actual operator inputs belong in `installation/{schema,registry,render}.py`; its strict shapes must continue to reject unknown fields. |
| Environment bindings | No portal, provisioner, Helm, or Kubernetes environment change is required. If scope later needs one, use the owning installation inventory and existing `config/_env_manifest.py` generator. Do not add an independent env schema or scanner credential binding. |
| Secrets and OS exposure | Keep state, plans, credentials, presigned URLs, and log contents out of argv, shell tracing, SARIF, and public artifacts. Use existing bootstrap private-file/stdin transport if operational verification requires secrets. Quote target/output paths and pass dynamic workflow values as environment data. |
| Errors and observability | Shell nonzero status and per-target SARIF are the scan error contract. Preserve diagnostics without swallowing errors. Existing `shared/cloud/exceptions.py`, `shared/api/errors.py`, and `shared/log_sanitize.py` remain the application boundaries; this issue needs no new API envelope, logger, or exception class. |
| Persistence and lifecycle | Existing Terraform state roots, `engine-state/moved.tf`, bucket lifecycle rules, CMEK migration, and RDS teardown ownership. No Django model, operation schema, controller, repository layer, or application data migration is needed for scanner enforcement. |
| Repository enforcement | `deploy.yml` calls `_quality.yml`; preserve upstream failure propagation and event/runner boundaries. The ADR registry, exception expiry, invocation parity, secret hygiene, quality ownership, and documentation checks remain active. |

The storage extension seam is an owning-module target bucket reference and stable source prefix, with readiness dependencies.
A future source bucket should need an owning-module binding and exact policy entry, not a scanner-framework change.
Retention belongs in existing typed lifecycle inputs; protection belongs in existing environment inputs.
Egress variation belongs in `installation/range_egress.py`, its renderer, and Terraform backstops under ADR-017, not a second policy vocabulary.
If scan targets are consolidated, keep one explicit owned-target list and one aggregation body without creating another configuration file.

## Verification and non-goals

Extend existing workflow/ownership tests and affected Terraform contracts, rather than adding a parallel test harness.
Reuse `test_quality_path_ownership.py`, `test_deploy_workflow.py`, and the skip-tests cases in `test_adr_guard.py`.
Exercise early and late findings, scanner errors, all-target execution, failure artifacts, and clean final status.
Mutations that restore exit-code zero, swallow status, or reintroduce skip gating must fail the targeted tests.
Terraform contract suites use mock providers and the canonical root/module inventory; new suites must be selected by that inventory.
The affected AWS storage/RDS modules and GCP Cloud SQL currently have `contract: deferred`; adding test files alone does not schedule them.

Include logging feature-flag combinations, exact delivery policies, version retention, role boundaries, and exception expiry in relevant contracts.

Structural checks cannot establish live log delivery, restored data, effective IAM, or absence of SQL text.
Keep live evidence private and distinguish source validation from deployment qualification.

Implementation must pass the full CI-level ADR guard, actionlint, recursive tflint, Terraform formatting/validation, and affected targeted tests.
Terraform Checkov must retain invocation parity with `platform/terraform/.checkov.yaml`, including the existing immutable-subject syntax adapter.
Do not weaken another scanner to make Trivy pass.
Keep local tests targeted and use CI for complete suites.

Non-goals are implementing #2563/#2564 in this preflight, applying infrastructure, performing data migrations, changing runtime identities, or approving release evidence.
No new requirement, external service, logging platform, hosting destination, public security record, or application contract is introduced.
No private pack content, source, or operational evidence belongs in configuration-scan artifacts or public guidance.
