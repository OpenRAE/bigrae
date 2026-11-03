# Tenant trial archive intake boundary (#2740)

Architecture preflight, 2026-11-03. The issue's supplied title, body and acceptance
criteria are the delivery contract. This is design guidance, not an implementation
plan or evidence that intake exists. No worker dispatch prerequisite is added.

## Ownership and facts that must stay separate

CMS owns tenant archive custody, its durable collection metadata and its public
service facade. A management command is a thin authenticated adapter to that
same service, following `cms/management/commands/register_pack.py`. Portable
run/evidence parsing belongs behind `shared.raes`; only that package imports
the RAES module family. Inject `shared.cloud.types.ObjectStorage`, selected by
`shared.cloud.get_object_storage`, rather than embedding a provider client.
Keep SQL custody metadata in the owning domain, not a new repository framework.
These paths are relative to `shifter/shifter_platform` unless stated otherwise.

The existing architecture model is ADR-001/024/027/031/043/066, enforced by
`.importlinter`, `scripts/check_layer_imports/layer_imports.yaml` and
`scripts/adr_guard`. Intake does not restore `cms.experiments`, its models,
flags, queues or executor. Engine continues to own native realization evidence;
consume existing public services or retained contract bytes, never Engine or
CTF models from CMS. Workspaces owns tenancy, not archive parsing or storage.

Keep these independent facts visible:

- **Byte collection:** every declared present member/chunk reached its exact
  durable destination and passed size/digest checks.
- **Evidence coverage:** required captures may have explicit loss, withholding,
  optional-unavailable or other upstream gap disclosures.
- **Scientific outcome:** the original failed, partial, inconclusive or successful
  run and attempt records retain their own meaning.
- **Cleanup:** a collection receipt permits disposal of the worker evidence copy;
  it proves neither trial success nor cloud cleanup, resource reuse or range READY.

A valid failed/partial record is collectible. Preserve its original upstream
accounting and loss disclosures. A missing declared file/chunk prevents a
committed collection receipt; recording a gap does not turn those missing bytes
into a successful empty capture. A verified archive containing an honestly
disclosed capture failure may be retained without claiming complete evidence.
No receipt means keep the worker copy for recovery. This service does not destroy
workers or decide whether their compute resources are safe to reuse.

## Contract custody and validation

Reuse released RAES run, evidence, artifact/checksum, trial provenance, attempt,
cleanup and accounting contracts and the producer's checksummed sealed archive
inventory. `shared.raes.runs.RunDescriptor` represents parameter selection only;
it is not an archival run. `RaesOperationRecord` is a bounded, redacted operational
sidecar, not a full scientific record store. Neither `shared.audit`, provisioning
completion receipts nor `TenantPackArchive` is the trial archive schema.

The frozen environment now matches RAES 10.6.0 and environment packs 7.2.2.
Released RAES models own scientific record validation and trial joins.
The producer's existing `aptl.run-seal/v1` format owns the sealed inventory.
The intake validates that existing wire format without importing producer internals.
It adds no second scientific schema or fallback import.
The [custody design](trial-archive-custody.md) defines the implementation decisions and references.
New LilRAE commands remain outside the acceptance dependencies.

Validate the original bytes through the released public contracts behind one
shared seam. CMS binds the authenticated tenant and independently supplied
expected experiment/plan/entry/run/attempt identities to every relevant record
and reference, including upstream versions/digests. Do not accept the archive's
self-declared identity as the expectation. Reject wrong-run artifacts, dangling
or conflicting joins, duplicate record identities and inconsistent attempt
accounting. Use the public validation suitable for partial archival records;
scientific eligibility or successful-run validation must not become a condition
for retaining failed evidence. Do not disable structural validation to admit it.

`shared.raes.json_ingress.parse_bounded_json_object` is the incumbent bounded
JSON ingress; preserve its rejection of ambiguous/duplicate keys and non-finite
values. Its current facade exposes only a byte bound; route a necessary
upstream nesting limit through that same facade, not a second JSON parser.
Released models own portable field and semantic validation. Native
tenant binding, archive containment, destination verification and authorization
remain Shifter responsibilities, not duplicate scientific validators. Bound
individual metadata/record documents as well as nesting, entry count, compressed
and expanded bytes, individual artifacts and temporary-disk consumption. Stream
artifact/chunk digests and transfers; never load the study or large traces into
one JSON object or `BytesIO`.

The containment incumbent is `shared.raes.object_source`: private staging,
source-version-bound download, rejected links/special files/traversal and the
stdlib tar `data` filter. Its pack-root/`pack.yaml` policy is pack-specific and
must not be imposed on trial archives. Its `getmembers()` prescan is not a
streaming entry-count limiter: enforce bounds while traversing untrusted entries.
Reuse or narrowly extract applicable safety mechanics rather than copying a
second extractor. Reject absolute and escaping paths, backslash/drive aliases,
duplicate normalized names, file/directory collisions, symlinks/hardlinks,
devices/FIFOs, malformed/truncated streams and undeclared files. Archive entry
names, ownership/modes and embedded URIs cannot select host paths or permissions.
Do not fetch referenced URLs, invoke external extractors, compile SDL, install
adapters, import pack code or execute archived content while validating records.

Retain byte-exact original records, hydrated SDL/provenance, participant
configuration and prompt commitments, authorized delivered content, full declared
participant/tool traces, security-service exports, native realization evidence,
usage, capture-loss and cleanup records. A summary, prefix of a trace or terminal
attempt alone is insufficient. Check the inventory and its references, not a
hardcoded shortlist of filenames. Respect upstream sensitivity/redaction and
disclosure contracts. Credentials remain excluded. The sidecar payload allowlist
in `shared.schemas.raes_operation` must stay narrow: it cannot be applied to
delete legitimate prompts/traces from this restricted archive, nor widened to
publish them. Do not silently redact, normalize, reserialize or reseal originals
after verifying their inventory. Invalid secret-bearing input must fail closed;
producer correction follows the published redaction/version contract, not an
intake rewrite of committed bytes. Public fixtures and repository records remain
synthetic; restricted tenant custody is not permission to publish private content.

## Durable publication, retry and retention

Use the existing Django transaction/unique-constraint/replay-conflict pattern in
`shared.raes.operations` and the reserve-before-I/O, reauthorize/fence-before-commit
pattern in `cms.services._tenant_pack_upload_journal` and `_tenant_pack_upload`.
Reuse the pattern, not pack-removal rows or their deletion policy. Persist exact
transfer custody before a cloud write so a crash, timeout or lost acknowledgement
leaves an operator-visible incomplete collection with known owned objects.
Keep long transfer/readback work outside SQL locks. Fence concurrent finalizers,
stale leases and retention cleanup; a late writer cannot regain publication
authority. `cms.services._scoped_uploads._reserve_upload` is the incumbent
scoped byte-reservation pattern: bound concurrent temporary and retained storage
use as well as per-archive size; do not repurpose its agent-specific budget rows
or quota setting. Avoid a new generic workflow, queue or orchestration engine.

The commit boundary is one SQL transaction publishing the durable collection
receipt and its verified object references after all destination bytes have
passed verification. Object storage and SQL are not one distributed transaction.
Use fresh server-owned transfer/object keys and immutable committed references;
an interrupted transfer can retry without overwriting any original. Read back
with `head_object` / `download_object(expected_identity=..., max_bytes=...)` and
hash in bounded chunks unless the adapter supplies an equally strong verified
digest for the exact stored version. Source hashes, object existence, length
alone and S3 multipart ETags are not destination checksum proof. Preserve the
original archive bytes and sealed inventory identity; semantic JSON equality or
recompression must not excuse changed delivered bytes.

**Provider gotcha:** the `ObjectStorage.copy_object_conditional` protocol promises
destination absence, but the current AWS implementation only applies
`CopySourceIfMatch` and relies on a fresh server-generated destination key.
GCS applies both source-generation and destination-absence preconditions. Never
treat the AWS method as atomic create-if-absent at a deterministic receipt key.
Unconditional `upload_file`, `copy_object`, and the existence shortcut in
`shared.raes.content_payload.promote` likewise do not establish receipt immutability
or destination verification. Stay within the incumbent storage abstraction; a
necessary capability correction belongs there with both adapter contract tests,
not in a service-local SDK bypass.

The durable uniqueness boundary includes tenant ownership and the expected
experiment/plan/entry/run/attempt reference, with contract versions where the
published identity requires them. Same committed identity and same verified
bytes returns the same receipt, including after an acknowledged commit whose
response was lost. Changed bytes conflict; a new delivery/request ID cannot evade
that rule. Preserve valid upstream record versions without turning receipt IDs
into scientific versions. Persist only custody, verification, gap and retention
metadata natively; original scientific records stay in the archive. A checksum
proves integrity, not producer authority or truth of a scientific claim.

Pin the destination configuration and retention policy for each admitted transfer
and receipt. A configuration change must not redirect recovery or retrieval.
Policy must define expiry, any supported hold/keep behavior, who may change it,
and physical deletion/retry behavior, including noncurrent cloud versions.
Separate abandoned-transfer cleanup from committed archive retention. Delete
only exactly owned objects, never a tenant-wide prefix or another collection's
shared bytes. Pack uninstall, range deletion, sidecar expiry and worker teardown
must not cascade into archive deletion. Reads obey policy despite purge lag;
retain body-free disposition metadata sufficient to prevent expired receipts
from authorizing retrieval or identity reuse with changed bytes. Do not discard
recovery custody after an ambiguous deletion or late cloud write. Bucket
lifecycle/IAM must not invalidate the promised retention window or permit workers
to overwrite committed evidence.

## Cross-cutting layers the implementation must pass

| Layer and canonical incumbent | Required behavior |
| --- | --- |
| Authentication and policy: `shared.credentials`, `shared.api_tokens.authentication`, `shared.authorization`, `shared.identity_scope`, public `workspaces.services`; CMS `_content_authority` admission/fence pattern | Authenticate actual proof; resolve SQL-owned account/organization/workspace ancestry; enforce the credential ceiling and exact operation through existing policy. Use the existing scoped content read/manage operations where applicable, rather than a parallel experiment role system. Recheck live authority before publication and fence local credential/scope state in the commit. Authorize listing, gap visibility, retrieval and retention independently. Tenant IDs, archive claims, staff status and credential UUIDs alone grant no access. Unknown/foreign receipt lookups do not reveal existence. Paginate tenant-filtered SQL custody metadata; do not enumerate buckets. |
| CLI and OS: `shared.api_tokens.cli.credential_from_file`, `cms/management/commands/register_pack.py`, `shared.raes.object_source` | Use the incumbent owner-only `0600`, no-follow, bounded regular-file credential transport; no token argument, environment dump or impersonation by username. Arguments carry safe IDs and file locators, not prompts, bodies, credentials or signed URLs. Stage evidence privately with bounded disk use and guaranteed cleanup. No shell interpolation or execution of archive data. A command and future dispatcher call the same authorized service. |
| Configuration and environment shapes: `config._cloud`, `_runtime_env`, `_product_env`, split settings, `_env_manifest` / `env-manifest.json`; `shifter/installation/{schema,registry,runtime_inventory,runtime_inventory_gcp,runtime_inventory_aws}.py`, `settings_gcp.GcpBackendSettings` / `settings_aws.AwsSettings` and `bundle_{gcp,aws}`; `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/aws_eks.py` runtime renderer, Helm templates / `values.schema.json` | Require an explicitly configured approved tenant destination and explicit archive retention; absent/invalid config disables intake with a safe error. `STORAGE_BUCKET_NAME` and `RAES_PACKAGE_BUCKET` are incumbents, not authorization to auto-select a trial destination. Reuse typed settings, backend STORAGE capability, alias conflict handling, manifest generator and deployment renderer. The root installation schema only validates the settings mapping; its selected backend bundle validates allowed keys and values with closed settings models (`extra="forbid"`). Any new bounds/destination/policy knobs must agree across that bundle, env-key inventories and deployed bindings; helper reads need explicit manifest entries when not extracted. Validate positive operational bounds and unambiguous retention values. Do not add a provider selector, local env parser, silent fallback or committed renderer-owned env value. |
| Cloud IAM and secrets: existing AWS owner checks and GCP configured project/identity; `shared.cloud.sensitive_env`, Kubernetes `_secrets` / `_job_manifest`; tenant storage Terraform | Keep writes/reads/deletes within the approved bucket/prefix and native tenant ownership; credentials use installed workload identity/secret references. Evidence URIs and submitted bucket names cannot redirect access. No new storage service, bucket creation, egress or broad worker role. If runtime env bindings are touched, sensitive values use the incumbent Secret-reference path; keep non-root/read-only/seccomp runtime controls. No dispatch change is required here. |
| Exceptions and public envelopes: `shared.cloud.exceptions` (`CloudStorageError`, `ObjectPreconditionError`), shared `ValidationError`/`CMSError`, tenancy errors, `shared.errors`, `shared.api.errors`; HTTP `ClosedJSONParser` / `ClosedSerializer` if later needed | Translate foreign parser/provider failures at their adapter, preserving validation, denied, conflict, transient/unknown-transfer and retention dispositions. Reinspect a precondition failure; do not blindly retry into overwrite or call it success. No duplicate hierarchy/envelope. Use fixed authored messages and safe `CommandError`; raw exception chains, Pydantic inputs, paths and provider diagnostics must not reach users. Truncation and `ValidationError.value` do not redact secrets. No HTTP upload endpoint is required by this issue. |
| Audit and observability: `shared.audit` (`AuditEvent`, `principal_actor_fields`, `audit_log`), `config.logging.ECSFormatter`, `shared.log_sanitize` | Record principal/scope, receipt/transfer correlation, dispositions, byte/member/gap counts and durations. Use existing strict audit semantics for custody mutations, in their SQL transaction, and body-free evidence for access/retention. No archive bodies in audit, logs, metrics labels, events, queues or DLQs. Escape untrusted safe identifiers; fingerprint sensitive ones. `safe_log_value` and `safe_user_message` are formatting, not confidential-data redaction. Existing cloud adapters log keys/exceptions: use opaque server-generated keys and check lower-level failure paths for leakage, not only the service logger. Expose pending/failed collection and retry state through the service/command for recovery without a new dashboard or monitoring sink. |

Retrieval must resolve committed, authorized, unexpired custody metadata rather
than accepting a caller's object key. Preserve exact object version/integrity on
download. Do not introduce public ACLs or unrestricted signed links; any approved
download capability must be short-lived and bounded by access/retention policy.
Untrusted filenames and media types cannot create response-header injection or
active inline content; reuse `shared.s3.sanitize_s3_filename` for display names
with the stricter attachment-header restrictions already used in `ctf.s3`,
without importing that CTF provider client. The existing storage signed-download
method does not bind an expected object version or revocation state; it is not
a substitute for authorized, version-checked retrieval.

## Extension seam and verification boundary

The next consumer is a dispatcher; it supplies authenticated scope, expected
identities and an archive stream/reference to the same service. The useful
parameters are the injected storage adapter, explicitly approved destination,
archive resource bounds, published contract/version selection and retention
policy. Keep them outside scientific records. Another trace kind or provider
should use upstream inventory declarations and the existing storage adapter,
without re-editing a filename whitelist, canonical scientific schema or workflow.
There is no need for an archive plugin registry or universal ingestion framework.

Use real synthetic archive/chunk bytes through the real service and shared
validators. Incumbents are `tests/shared/raes/test_object_source.py`,
`tests/shared/cloud/test_{aws,gcp}_storage.py`,
`tests/cms/test_tenant_pack_upload{,_journal}.py`, principal/credential tests,
`tests/shared/test_api_errors.py` and config/runtime-inventory tests. Mock the
external SDK boundary, not first-party validation. Cover the issue's interrupted
transfer, retry, wrong-run joins, corruption, missing chunks, duplicate delivery,
unsafe paths, unauthorized access and retention cases. Also establish concurrent
same/different-byte finalization, failure after destination write and SQL commit,
lost response, revoked authority, stale leases, cleanup races, exact destination
readback, failed/partial capture disclosure and no secret leakage. PostgreSQL
tests, following the existing tenant-upload/removal concurrency lanes, must prove
locking/uniqueness; SQLite is insufficient. Target mutation testing at digest,
identity, authorization, publish-before-verification and retention predicates.

Operator docs must describe the approved destination and policy configuration,
credential-file invocation, stable receipt/idempotency contract, gap versus
outcome semantics and recovery/disposal rules. Link user and technical docs from
their indexes and update `docs/adr/documentation-coverage.yaml` when delivering
this feature (ADR-022). Keep the one-PR scope independent of live VM dispatch,
new LilRAE commands, dashboards, analytics, warehouses and storage deployment.
Do not change producer scientific semantics, native realization authority,
shared audit retention or operational sidecar redaction/expiry for this feature.

For this documentation change the required check is
`python3 scripts/adr_guard/adr_guard.py --all --level ci`. The implementation also
uses targeted storage/intake/security/config tests, Ruff and layer/import checks;
any changed workflow, Terraform or chart must pass the stack-native checks in
`AGENTS.md` and `.gc/plan-rules.md`. Reuse existing CI quality ownership lanes,
not a new workflow or weakened guard. This preflight changes no runtime code and
claims no runtime, archive API or live-storage qualification.
