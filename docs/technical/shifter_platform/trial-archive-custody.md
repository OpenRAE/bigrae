# Trial archive service contract

Reference for archive intake, identity, retention limits, and custody receipts.

The public `cms.services` facade provides central archive custody.
Portable scientific contracts remain in the pinned RAES distribution.
CMS stores destination, transfer, and receipt metadata only.
Original scientific records remain byte-exact in approved tenant object storage.

## Service boundary

| Service | Authority | Result |
| --- | --- | --- |
| `configure_trial_archive_destination` | Installation and organization `manage_content` | Explicit bucket, prefix, retention |
| `intake_trial_archive` | Organization `manage_content` | Committed receipt or bounded error |
| `list_trial_archives` | Organization `read_content` | Up to 100 receipt and transfer projections |
| `retrieve_trial_archive` | Organization `read_content` | Verified private file at a new output path |
| `purge_trial_archives` | Organization `manage_content` | Count of physically removed expired objects |

All services require an authenticated `CredentialContext`.
They resolve current tenancy and evaluate the credential ceiling through the existing native authorization boundary.
Tenant identifiers and archive contents grant no access.

The management command uses this same facade.
Experiment admission reuses the scientific-record credential rejection rules before retaining inputs in SQL.
The admission check exhausts the same recursive record visitor, so nested credential fields are checked even when no evidence references are collected.

The authorization surface inventory records its credential transport and per-operation authority.
Experiment dispatch calls the same intake service with `run_record_only`.
That mode verifies containment, the sealed bytes, and the run record, and reads no other record.
The private `read_archived_run` operation retrieves a committed archive and returns only its run record.

`TrialArchiveIdentity` carries expected experiment, plan, entry, run, and attempt identifiers.
It also binds the admitted plan digest, entry digest, and run version.
The inventory cannot supply these expectations.

The experiment identifier selects the plan's study reference, or its authoring-input reference when no study exists.
RAES validates admitted plan digests, run models, attempt accounting, and cleanup joins.
The intake boundary verifies record references against the retained byte inventory.

Inventory media types and scientific record roles select the parser, including for alternate filenames.
Run, version, and execution-attempt bindings use the same checks for JSON and JSON Lines records.
These checks also cover nested current-run records.

Historical reference objects retain their original meaning.
The published admitted-plan validator governs other planned entries.
YAML, including hydrated SDL, uses the public bounded RAES fragment loader.

Credential and nested ownership checks apply without changing accepted original bytes.
It does not calculate metrics, compile SDL, execute adapters, or fetch evidence URLs.

## Archive boundary

The input is an existing sealed tar or gzip-compressed tar export.
One run directory contains `manifest.json`, `seal.json`, and the sealed inventory members.
The optional `checksums.sha256` document uses the exporter's standard checksum lines.

The seal uses the LilRAE `aptl.run-seal/v1` format or the BigRAE `bigrae.trial-seal/v1` format.
The original manifest uses the released `experiment-run/v1` contract.
A record under the BigRAE seal must be `partial`.
The inventory must include the original manifest and every declared evidence byte reference.

Missing declared bytes prevent a receipt.
Honest unavailable or partial evidence disclosures remain original records.
Published capture specifications identify declared capture requirements.

Missing specifications, absent capture records, and empty required content add coverage gaps.
Multiple attempts use their accounting evidence links and capture intervals.
Evidence from one attempt cannot conceal another attempt's missing capture.

Every attempt also checks each record timestamp against its required capture window.
These gaps do not alter the original scientific outcome or prevent retention of available bytes.

| Resource | Maximum |
| --- | --- |
| Compressed input | 16 GiB |
| Expanded tar stream | 64 GiB |
| Tar members | 20000 |
| One JSON document | 4 MiB |
| One YAML document | 4 MiB, plus upstream SDL parser limits |
| Retained structured metadata | 32 MiB |
| One tar extension header | 1 MiB |
| Combined tar extension headers | 4 MiB |
| One JSON Lines object | 4 MiB |
| Lines in one structured trace | 1000000 |
| Stream chunk | 1 MiB |

Large trace artifacts are hashed and transferred in chunks.
Containment and inventory validation precede a second streamed scan of declared structured formats.
Oversized JSON documents are rejected, including scientific records and credential-bearing documents.

Large traces can use bounded JSON chunks, JSON Lines, or another declared artifact stream.
A member with the `evidence-blob` role is a raw capture. It is hashed and retained, but never parsed as a document.
JSON Lines and NDJSON traces contain one UTF-8 object per line.
The parser rejects blank lines, credential fields, and foreign run bindings.

Execution-attempt references must resolve to retained run accounting.
It joins byte references to the inventory.
Scientific records retain the shared metadata budget and use released RAES validation.

The service stages one bounded archive and one readback on private temporary disk.
Provision at least twice the maximum compressed archive size in temporary disk capacity.
Archive content is never extracted to host paths.

The standard tar reader receives a standard buffered reader over the bounded raw stream.
Its metadata hooks reject oversized extension bodies before allocation.
Each scan keeps only typed byte indexes and bounded structured metadata.

Links, traversal, duplicate names, special files, sparse files, and undeclared bytes are rejected.

A LilRAE trial seal (`lilrae-trial-record/v1`) has no RAES plan or run record.
Intake binds it through `trial/record.json`: its run and attempt identities must equal the expected identity.
Its plan metadata is empty. Every inventory member and checksum is still validated.

## Receipt and failure semantics

The receipt is the SQL commit after destination readback succeeds.
The destination reference includes the observed object version.
Byte count and SHA-256 must match the original archive.

Existence, source hashes, and multipart ETags alone do not establish this result.
Receipt uniqueness covers organization and all five expected identifiers.
It also includes the run version.

Changing a plan or entry digest cannot evade that identity's conflict check.
Identical bytes return the same receipt.
Different bytes conflict under the committed identity.

Retries and concurrent deliveries cannot overwrite a committed object.

The collection projection includes `id`, `transfer_id`, `collection_status`, `archive_digest`, and `expected`.
It also includes `worker_copy_disposable`, `run_status`, `outcome_status`, `evidence_complete`, `gap_count`, and `expires_at`.
Incomplete transfers have a fixed `failure_code` and no disposal authorization.
Only a committed, unexpired receipt permits disposal of the worker's evidence copy.
This permission makes no scientific-success or resource-cleanup claim.

Each transfer pins its approved destination and retention policy before storage I/O.
A lost upload acknowledgment retains an unknown transfer outcome.
The caller can retry without reusing its object key.

Uncertain transfers remain operator recovery records.
Purge does not delete them automatically.
Finite retention covers settled duplicate and abandoned objects too.

Cleanup fences publication before deleting their recorded object keys.
Purged rows cannot block later cleanup pages.
Expired receipts remain identity tombstones.

Reads stop at expiry while physical deletion retries continue.
Cloud version lifecycle remains the storage operator's responsibility.

Strict audit records contain opaque transfer or receipt identifiers and dispositions.
They exclude prompts, traces, parser inputs, and provider error bodies.
No new HTTP endpoint, role system, storage service, worker dispatcher, or analytics schema is introduced.

See [operator instructions](../../how-to/retain-trial-archives.md) and the [architecture design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/trial-archive-custody.md).

## Derived experiment exports

The batch export service uses the custody inventory and verified retrieval
operations. Inventory pages have stable ordering and can select the retained
experiment identity. Custody also owns publication of the derived manifest and
CSV/JSON indexes to the current approved tenant destination.

This write requires
current tenant content-management authority. The content digest names each export;
original archives remain unchanged. The manifest is published after the indexes
verify.

Each derived file has its own transfer journal and pinned expiry. The existing
settled-write fence and purge operation enforce retention for these objects.
Archive inventory excludes records marked as derived exports.

See [the result export design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/experiment-result-exports.md).

Export inspection reuses the complete archive validator. It optionally retains
usage-bearing JSON Lines records under the existing metadata bound, with their
original member and line references. Intake keeps its existing scientific-only
metadata retention. Unsupported export metadata sizes cause an explicit refusal.

Validated intake also retains bounded plan and entry identity, coordinates and
replacement origin in `TrialArchiveTransfer.plan_metadata` before upload. It
contains no configuration bodies and grants no custody receipt. Exports use it
to report unavailable replacement collections; unknown legacy associations
require matching verified evidence or an explicit refusal.

Derived file publication lives in `_trial_archive_exports` behind the existing
custody service entry point. It reuses the same authority, verification, audit
and retention primitives; record formatting remains in the export record module.
