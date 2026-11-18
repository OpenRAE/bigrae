# RB003: Orphaned range resources

Applicability: GCP/GCE observation; AWS observation with a limited legacy tool.
Operator: platform and range owner. Verified: 2026-10-23.

Use the [shared operating contract](index.md#shared-operating-contract) before investigation or recovery.

## Symptom

Provider resources carry Shifter ownership labels but no active range owns
them, or a terminal range still has instances, disks, networks, or secrets.

## Investigation

1. Stop changes to the affected range. Export a redacted inventory with request ID, operation ID, generation, resource type, and ownership labels.
2. Compare provider inventory with Engine ranges, immutable operation inputs and
   results, launch intents, cleanup verification, and provisioner state. Do not
   use the CMS projection alone as lifecycle authority.
3. On GCP, query resource types separately with purpose-scoped `gcloud` list or describe commands. Do not broaden IAM or enable APIs to assemble an incident inventory.
4. On AWS, `shifter-ops` can classify EC2 candidates, but its current
   `reconcile_ranges execute` path terminates instances before non-transactional
   direct SQL updates. Treat it as unqualified for recovery; use observation
   output only.

## Resolution

There is no approved provider-neutral orphan mutation. Preserve evidence. Ask the existing owners to quarantine affected networks and credentials. Escalate for a reviewed cleanup plan. The plan must name each resource, durable owner, action order, rollback boundary, and independent readback. Never delete by name
prefix, edit status rows, or remove Terraform state to make inventory appear
clean.

## Prevention

Require ownership labels and operation IDs on every provider effect, make
cleanup verification part of lifecycle completion, and run scheduled residual
inventory comparisons. A successful destroy must prove both durable convergence
and absent provider resources.

Escalate every confirmed orphan; this runbook intentionally has no direct
delete command.
