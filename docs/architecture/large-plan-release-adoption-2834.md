# Large plan release adoption (#2834)

## Decision

Use the released pair `raes==11.0.1` and `raes-env-packs==7.2.3` in
the platform and preparation environments. RAE 11.0.1 fixes bounded
verification for large secret plans. Keep the existing verification rules.

This change uses ADR-024, ADR-031 and ADR-032. The architecture model remains
`raes-plan-accessor-boundary/v1`, enforced by ADR guard and import-linter.
Only `shared.raes` imports RAE. The provisioner continues to read plain data.
No new service, setting, schema, capability or deployment route is needed.

## Data flow and checks

Released wheels → exact manifests and generated locks → platform planning
and verification → immutable serialized plan → standalone provisioner reader.
The preparation image uses its separate generated lock for the same pair.
Existing source custody, adapter isolation, operation identity, evidence and
provider checks remain in force. This change grants no new cloud access.

Fresh realization accepts only the reviewed `raes-provisioning-plan-v2` /
`11.0.1` pair. Add `v2 / 10.7.2` to the existing cleanup-only list.
Keep the older reviewed cleanup pairs and their current wire checks.
Never rewrite retained plans or relax their authority checks.

Before an update, drain old planning and realization work and settle its
completion results. Do not run workers with different producer versions on
the same queue. Customer tenant updates require separate approval.

## Validation

Use existing exact-pin, serialized-reader, experiment admission and native
conformance tests. Add a synthetic large secret plan at the current
no-dispatch boundary. Verify that retained 10.7.2 plans are cleanup-only,
retain their bytes, and still reject malformed authority metadata.
Mutate producer admission and the retained cleanup entry to check the tests.
Run ADR guard, import-linter and the affected writing and Python checks.
Test the release pair in the test tenant before any customer update.

RAE 11 stores derived digests separately from raw corpus fixtures. Tests that
use those fixtures first apply the released `seal_payload` helper. The normal
released model then validates the complete synthetic record. Persisted records
continue to require their original digests; admission must not repair them.

The two maintenance workers with small CPU limits must also complete cold
startup before their heartbeat checks expire. Use the existing one-core worker
limit for bootstrap pruning and pack removal. Keep CPU requests, memory limits
and all health checks unchanged. Test the combined update before launch.

The result applier must validate the retained large plan when it processes a
snapshot and terminal result. Use a 512 MiB memory request, a 2 GiB memory
limit and the existing one-core worker limit. The previous 512 MiB limit can
terminate the process before it commits the result. Pending inbox rows remain
the recovery input; never mark them applied or mark the range ready manually.
Verify recovery with the original pending results and the existing range.
