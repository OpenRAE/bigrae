# BigRAE Engine

Reference for realized range state, device operations, and terminal access.

## Responsibility

- Range lifecycle (provision, cancel, destroy)
- NGFW lifecycle (provision, deprovision, instance management)
- Subnet allocation
- Scenario configuration
- SSH terminal connections
- Container task orchestration (via cloud adapter)

## Models

| Model | Purpose |
|-------|---------|
| `Request` | Provisioning request container (correlation via UUID) |
| `Range` | User's cyber range with lifecycle status and timestamps |
| `Instance` | Materialized VM instance with Pulumi/Terraform state |
| `App` | Materialized app (NGFW, etc.) with infrastructure state |
| `Subnet` | Allocated subnet with CIDR and routing configuration |

## Service Interface

Signatures below abbreviate optional arguments.
Native operations require current admitted credentials and exact resource custody.
The `engine.services` exports and their typed definitions are authoritative.

### Range Operations

| Function | Purpose |
|----------|---------|
| `create_raes_range(...)` | Create an admitted native RAES generation |
| `destroy_range_by_request(request_id)` | Destroy range by request UUID |
| `cancel_range_by_request(request_id)` | Cancel in-progress provisioning |
| `get_range_status(range_id)` | Get status, instances, progress |
| `pause_range(range_id)` | Pause range instances |
| `resume_range(range_id)` | Resume range instances |

### Terminal Operations

| Function | Purpose |
|----------|---------|
| `connect_terminal(...)` | Resolve admitted SSH access for the exact guest |
| `get_rdp_connection_info(...)` | Resolve admitted Guacamole RDP access |

### NGFW Operations

| Function | Purpose |
|----------|---------|
| `create_ngfw(request_spec)` | Start NGFW provisioning |
| `destroy_ngfw(request_id)` | Destroy NGFW |
| `start_ngfw(request_id)` | Start stopped NGFW |
| `stop_ngfw(request_id)` | Stop running NGFW |

`complete_ngfw_setup` is not exported or implemented in the current Engine service.
Do not use it as an integration operation.

### Internal Services

These implementation modules are private to Engine.
Other layers use the `engine.services` facade; adapters use the public SDK.

| Module | Purpose |
| --- | --- |
| `services/_subnet_coordination.py` | Native subnet allocation coordination |
| `services/_raes_range.py` | Native RAES range creation and immutable bindings |
| `services/_operation_apply_domain.py` | Validate and apply accepted native operation results |
| `ecs/` | Existing task-control adapter |
| `ssh.py` | SSH connection transport |
| `secrets.py` | Provider secret lookup |

## Event Handling

Provisioner Jobs read immutable operation inputs and append bounded results.
Engine validates result identity, generation, ownership, and operation family before applying state.
The provisioner does not write arbitrary range lifecycle state directly.
Engine commits accepted state, audit, and outbox events through its owning services.
CMS mirrors accepted results; Mission Control delivers notifications.
See [lifecycle contracts](identity-lifecycle-contracts.md) for the complete result and cleanup flow.

## Range warm pool (#28, ADR-039-R11)

The warm pool keeps system-owned, pre-provisioned range generations that an initial
launch can atomically claim, reducing cold-start latency without bypassing capacity,
tenancy, or lifecycle controls. Its architecture is fixed by
`docs/architecture/range-warm-pool-preflight-28.md` and the optional
`range-warm-activation/v1` capability in `docs/architecture/provider-neutral-range-substrate.md`.

Key seams:

- **Ledger (claim authority).** `engine.models.WarmRangeGeneration` is the row-plus-
  constraint claim authority. Its state (`provisioning`, `ready`, `claimed`,
  `activated`, `unhealthy`, `retiring`, `terminal`) is *private* allocation state, deliberately
  distinct from `Range.Status`: a warm-prepared range may be Engine-`READY` while the
  pool treats it as claimable only when the ledger row is `ready`.
- **Atomic claim.** `engine.services.claim_ready_generation` transitions one ready,
  exact-`compatibility_digest` generation to `claimed` under
  `select_for_update(skip_locked=True)`, giving one-winner semantics, with a partial-unique
  `claimed_by_request_id` constraint as the database backstop. The CMS launch path
  wraps the claim with the ownership rehome and commits before enqueuing activation.
- **Compatibility.** `shared.warm_pool.compatibility` computes the canonical digest
  (registered package + lock digest + admitted placement/posture) that both the
  reconciler and the launch claim compare. Warm eligibility is RAES-native only (the
  ownership-neutral `operation_input`). The loaded package and lock digests must
  match the selected compatibility key before a reservation is made.
- **Activation.** The provisioner `raes-range activate` operation scrubs every
  pre-claim credential/VPN/access identity, realizes the claimant's fresh access, and
  negatively verifies the prior access is revoked (`shared.warm_pool.activation_input`,
  provisioner `raes_gcp_activate*`). GCE is warm-capable; AWS/GDC report the capability
  unsupported and cold-fall-back.
- **Reconciler.** `cms.services.reconcile_warm_pool` (worker
  `reconcile_warm_pool`) replenishes shortfalls, retires expired/incompatible/excess
  and unhealthy generations through canonical `destroy`, and releases capacity only
  after provider absence is observed. Engine reserves the generation, global and
  bucket counts, and capacity draw in one database transaction. Provider work
  follows that commit. An active policy requires the non-secret
  `WARM_POOL_SERVICE_CREDENTIAL_UUID` reference. The referenced active service
  admission supplies the installation-scoped `installation.launch_range` authority;
  no dummy human, personal workspace, or stored cloud key owns preparation.
- **Retained recovery.** The production `reconcile_warm_pool --loop` worker
  advances pages of at most 100 retained obligations, including disabled or
  removed buckets. The cursor wraps after the last page. A one-shot invocation
  covers only one page. Unknown cleanup retains the same resource generation
  and schedules another exact-origin destroy operation after a delay that grows
  from 60 seconds to one hour. Old operation inputs and results remain immutable.
  Capacity stays held until current-generation absence is verified. Activation
  timeout starts at `claimed_at`, independent of the age of pool preparation.
- **Observability.** `shared.warm_pool.metrics` publishes gauges and claim outcomes
  to the `Shifter/WarmPool` namespace; warm lifecycle events are audited under the
  `warm_*` `AuditAction` vocabulary.

See [identity and lifecycle contracts](identity-lifecycle-contracts.md) for the
DFDs, lock order and recovery tests. Concurrent workers must use the same policy
snapshot to enforce the same limits. Stop workers with an old configuration
before treating a reduced limit as installation-wide.
