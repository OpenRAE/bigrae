# Publish a new range's parent before launch confirmation

Native creation retains the public range UUID, exact account ancestry, owner, generation and creation receipt. It does not publish the range's parent to the permission service. Normal range reads therefore deny an otherwise valid range.

Commit strict creation audit with the native range and CMS binding. After that transaction commits, publish the exact parent through the existing `HierarchyRelationshipChange` contract and confirm primary readback. Recheck the SQL snapshot after provider I/O. Require a matching native creation receipt. Keep provisioning deferred until publication succeeds. The existing creation receipt is the durable recovery input; do not add a second range ledger or derive permissions from ownership.

The Engine service owns publication. CMS calls its public facade outside its runtime transaction. A targeted management command uses the same service to repair an existing range. Repeated publication is idempotent. A missing receipt, changed custody or missing readback stops confirmation and dispatch. Installation-owned warm ranges have no customer parent and keep their existing path. No user grants or permission checks change.

Validate successful publication, write acknowledgment loss, absent readback, changed custody and the transaction boundary with synthetic fixtures. Verify the correction on the existing live range.
