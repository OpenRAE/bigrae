# Retry-safe range operations

Explanation of retry identity, immutable intent, and verified cleanup.

Architecture for the retry-safe public range-operation surface and truthful
cleanup outcomes. Decision of record: **ADR-063**; design guidance:
`docs/_deprecated/architecture/public-range-operations-preflight-2086.md` (issue #2086).

## Retry identity

The public retry identity is `(deployment_scope, actor_key, action, caller_key)`:

- **deployment_scope** is server-owned, resolved by
  `shared.deployment.resolve_deployment_scope()` from the deployment's cloud
  project (else a configured deployment name)—never a hostname, `ENVIRONMENT`
  label, workspace UUID, or catalog id. One deployment is one customer boundary backed by PostgreSQL (ADR-054). Each binding records deployment scope to detect a database restored or cloned into another deployment.
- **actor_key** identifies the native initiating principal. Session and personal credentials for that principal share retry identity. Each credential must still pass its current checks.
- **action** is `<resource>:<operation>` (a launch is `raes-range:provision`).
- **caller_key** is the bounded, caller-supplied key.

## Immutable-intent binding

`shared.operation_intent` owns the intent-projection version
(`INTENT_PROJECTION_VERSION`, distinct from the HTTP, RAES-producer, and
worker-envelope versions) and `canonical_intent_digest`, which validates a
projection (rejecting non-finite numbers and non-JSON shapes before hashing) and
reuses `shared.operation_envelope.canonical_payload_digest` for an order-independent
digest.

- The **caller intent** (the caller-controlled launch selections) is digested for
  the retry key so a replay recovers without recompiling the server-derived plan
  even after package/registry/default-configuration changes.
- The **compiled intent** (the full `OperationInput`—compiled plan plus
  artifact/configuration/delivery/participant-access bindings) is enforced by the
  engine: `engine.launch_intents.enqueue_provisioner_launch` compares the composed intent with stored immutable `OperationInput`. A changed internal replay conflicts before effects.

## Binding persistence and concurrency

`engine.models.PublicOperationRetryBinding`
(`engine_public_operation_retry_binding`) is an idempotency/admission **index**,
not a second execution ledger: it references the existing request/operation and
never owns lifecycle, status, or effects (ADR-043-R3/R4). A `UniqueConstraint` on
`(deployment_scope, actor_key, action, caller_key)` lets PostgreSQL arbitrate
concurrent first use.

`engine.retry_binding.bind_public_operation` recovers an existing binding, else
runs a caller-supplied `mint` inside the binding transaction and inserts the
binding. Concurrent first use has one winner. The loser's unique insert raises `IntegrityError`, rolling back its complete transaction and reservations. Outside the failed savepoint, it reads the committed winner and recovers or conflicts. Same-key contenders therefore converge on
one binding and one set of effects; the real-PostgreSQL proofs live in
`tests/engine/test_retry_binding_postgres.py`.

The launch orchestration is `cms.services.resolve_retry_recovery` /
`cms.services.bind_first_use_launch`; it reaches
the retry-binding primitives only through the `engine.services` facade (ADR-001)
and is called from `mission_control.api.ranges.LaunchRangeView` when an
`Idempotency-Key` header is present.

## Reauthorization

Replay, status lookup, and cancel reauthorize the *current* actor on every call
through the existing bearer-first authentication, exact scopes, and range
ownership. Actor identity is part of the retry key, so a replay can never recover
another actor's operation, and a revoked actor cannot authenticate.

## Provider inventory/readback evidence

Verified terminal cleanup requires an **independent inventory/readback** of the
owned provider resources, not a logical lifecycle status (ADR-063-R4). After deletion, the provisioner (`raes_gcp_inventory.inventory_raes_range_cell`) independently reads every owned instance, address, router, firewall, subnet, and network. NotFound means absent; a returned resource is a residual. A provider error means `INCOMPLETE`, never empty success. The terminal destroy payload carries bounded `cleanup_inventory`, validated by `shared.operation_result_payloads`. Engine records durable `RangeCleanupVerification` scope and observation time in the same transaction as the DESTROYED transition.

Immutable `OperationInput` preserves resource identity across producer and pack upgrades. Independent inventory detects residuals despite configuration drift.

## Truthful teardown and retention

All three cleanup consumers gate on the latest `RangeCleanupVerification` being
`VERIFIED_ABSENT`, never on logical status:

- **Verified-terminal reporting.** `engine.services.project_range_cleanup_outcome`
  reports `verified_terminal` only with `VERIFIED_ABSENT` evidence; a logical
  `DESTROYED` range with no evidence is `pending` with a
  `provider_inventory_unconfirmed` obligation, and `RESIDUALS_FOUND`/`INCOMPLETE`
  are `unknown` with residual obligations.
- **CTF capacity/linkage release.** `ctf.services.range.lifecycle` dispatches destroy and retains participant/range/reservation linkage while `destroying`. Capacity release and linkage removal require `ctf.signals.sync_ctf_participant_range_status` to receive DESTROYED with `cleanup_verified=True`. The CMS event handler derives that flag from inventory evidence. Revalidates #1919 (ADR-063-R5).
- **Retention pruning.** `engine.retry_binding.prune_expired_retry_bindings`
  deletes an expired binding only after verified cleanup absence. The `prune_retry_bindings` command uses this function. Unresolved recovery and residual evidence remain retained.
