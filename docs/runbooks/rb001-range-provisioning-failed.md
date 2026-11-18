# RB001: Range provisioning failed

Applicability: GCP/GCE primary; AWS optional. Operator: range and platform
operator. Verified: 2026-10-23.

Use the [shared operating contract](index.md#shared-operating-contract) before investigation or recovery.

## Symptom

A range remains pending or provisioning, the portal reports a failed launch,
or a provisioner Job finishes without the range becoming ready.

## Investigation

1. Record the request ID, current range status, operation ID, generation, and
   incident window from the authorized application view. Do not infer identity
   from a VM name.
2. Check the launcher, result applier, outbox, and reconciler workloads:

   Read-only command:

   ```bash
   kubectl -n "$NAMESPACE" get deploy \
     worker-provisioner-launcher worker-operation-result-applier \
     worker-outbox-drainer worker-reconciler
   kubectl -n "$JOBS_NAMESPACE" get jobs \
     -l app.kubernetes.io/component=pulumi-provisioner
   ```

3. Read bounded logs for those components and correlate only on the sanitized
   request or operation ID. Check whether the launch intent was claimed and the Job was admitted. Check for provider effects and a result in the Engine-owned inbox.
4. For GCE, inventory instances and subnets by Shifter ownership labels and
   compare their request/operation ownership with durable Engine state. A Job
   failure alone does not prove that no cloud effects occurred.

## Resolution

Use the portal's authorized retry or lifecycle action so the existing operation
identity, generation fence, launch intent, and result contract are preserved.
If the original operation may still be running, or ownership is ambiguous, do
not start another provisioner Job. Quarantine the range from new participant
use and escalate with the request ID, operation ID, Job status, and provider
inventory. Verify recovery through Engine state, CMS projection, cleanup
verification, and provider inventory.

## Prevention

Alert separately on launcher heartbeat, provisioner Job failures, pending
result-inbox age, outbox backlog, and provider quota/throttling. Keep image IDs,
runtime configuration, capacity, and admission policy in the protected deploy
readback. See [retry-safe range operations](../features/retry-safe-range-operations.md).

Escalate if an operation exceeds its lease or the Job and result identities disagree. Also escalate unowned provider effects or an unavailable application retry.
