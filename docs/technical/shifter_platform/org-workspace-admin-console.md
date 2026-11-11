# Organization/workspace admin console

Reference for the native account, organization, and workspace administration surface.
The SPA displays server projections; owning services authorize every read and command.
The [account administration reference](account-administration.md) describes cutover and recovery.

## Current-principal context API

`GET /api/v1/accounts/context/` returns the native principal context.
Fields include `principal_uuid`, `principal_kind`, `accounts`, `individual_account`, `installation_actions`, and `has_descendant_scopes`.
The context contains display and navigation hints, not credentials or permission grants.
`GET /api/v1/administer/scopes/?kind=organization` discovers independently readable organizations.
Use `kind=workspace` for workspaces. A parent read grant is not inferred.

The mounted source is `workspaces.api.account_admin_urls`.
The old `/api/v1/workspaces/context/` controller is not mounted by the current composition.
Native APIs accept admitted bearer credentials or current sessions as declared by each controller.
Browser mutations retain CSRF checks. Invalid bearer proof fails before session fallback.
Staff and legacy role flags do not replace current action policy.

## SPA shell

The `/administer` shell uses the common API client and TanStack Query.
Account context and action-derived hints determine visible navigation.
A route parameter or cached selection is not authority.
Parent changes reset child drafts; query keys include the exact resource path.
Policy mutations use the existing immutable retry identity and explicit reconciliation.
See the [authorization reference](authorization.md) for pending and unresolved operations.

## Organization profile & settings (issue #1939, PLAT-232)

The current profile routes use account and organization UUIDs.
Historical ADR-048 role-based admission is superseded by native policy.

### Organization authority (ADR-048)

Current services require the registered action on exact SQL-owned organization ancestry.
Membership and ownership remain separate facts.
Legacy `admin`, Django staff, and superuser values do not independently authorize profile access.

### Profile API

`GET/PATCH /api/v1/accounts/<account_uuid>/organizations/<organization_uuid>/` reads or updates the profile.
The existing profile serializers define `name`, `description`, `support_email`, and `support_url`.
PATCH changes only supplied fields; an empty supported string clears its value.
Unknown fields, invalid formats, and excessive lengths are rejected.
Strict audit records changed field names, not submitted values.

### SPA settings surface

The editor loads an authorized organization by public UUID.
It sends only fields changed from the loaded snapshot.
The shared error envelope supplies field errors.
The browser does not reconstruct authority from a role string.

## Workspace lifecycle (issue #1940, PLAT-233)

Workspaces owns creation, rename, archive, restore, and ownership facts.

### Two distinct authorities

Creation checks the parent's registered creation action.
A command on an existing workspace checks that workspace's action and exact ancestry.
Creation does not manufacture an administrator grant from a legacy role.

### Service (`workspaces/services/_lifecycle.py`)

Current native commands are exported through `workspaces.services`.
The `_account_policy_admin`, `_account_policy_lifecycle`, and `_account_policy_reads` modules own their implementation.
Mutations retain locks, last-owner checks, default-workspace protection, and strict audit.
Archive sets `archived_at`; it does not delete ranges or silently change their custody.

### Lifecycle API

All paths below are relative to `/api/v1/`.

| Path | Operation |
| --- | --- |
| `accounts/<account>/organizations/<organization>/workspaces/` | List or create |
| `accounts/<account>/organizations/<organization>/workspaces/<workspace>/` | Read detail |
| `workspaces/<workspace>/rename/` | Rename |
| `workspaces/<workspace>/archive/`, `workspaces/<workspace>/restore/` | Archive or restore |
| `account-workspaces/<workspace>/ownership/transfer/` | Transfer ownership |
| `workspaces/<workspace>/owners/` | List or add owners |
| `workspaces/<workspace>/owners/<principal>/` | Remove an exact owner |

Placeholders in this table are public UUIDs.
Use the generated contract for exact methods, request fields, and error responses.

### SPA lifecycle surface

The browser submits commands through the shared client and invalidates affected queries.
A visible action is a hint; the server rechecks current authority and invariants.
An uncertain policy publication retains its original receipt for recovery.

## Workspace membership & roles (issue #1941, PLAT-234)

Native membership associates a principal with an exact scope.
It neither stores the legacy role grant nor replaces authorization policy.
Ownership has separate commands and constraints.

### Consumed contract (unchanged)

The heading preserves an existing link; ADR-066 changed the underlying membership contract.
Current routes are relative to `/api/v1/`:

| Path | Purpose |
| --- | --- |
| `organizations/<target>/memberships/` | Organization principal memberships |
| `organizations/<target>/memberships/<principal>/` | Exact organization member |
| `workspaces/<target>/memberships/` | Workspace principal memberships |
| `workspaces/<target>/memberships/<principal>/` | Exact workspace member |
| `account-workspaces/<workspace>/membership/` | Current principal membership |
| `account-workspaces/<workspace>/memberships/leave/` | Explicit self-leave |

These routes use UUIDs, rather than legacy integer-user role commands.
See [invitations](workspace-member-invitations.md) for invitation lifecycle and acceptance.

### SPA membership surface

The server supplies bounded member projections and current action hints.
The browser offers self-leave through its dedicated command.
After a membership or ownership change, it refreshes affected scope and context queries.
Last-owner and lifecycle checks remain server-owned, including during concurrent changes.

## Workspace network egress policy (issue #1945, PLAT-238)

The zero-egress (no-NAT) range posture (#1171, ADR-026) is delivered as a
workspace-level policy. It reuses the one canonical vocabulary,
`installation.range_egress.RangeEgressMode`; a workspace stores only the
contextual subset `status-quo` (inherit the deployment baseline) or `none`
(zero egress), never CIDRs or provider configuration (ADR-017-R5).

### Backend spine

- **Persistence.** `Workspace.egress_policy` is a closed scalar with a database
  `CheckConstraint` and a compatibility default of `status-quo`. Native `workspace.manage_egress` policy authorizes `workspaces.services.admin_set_workspace_egress_policy`.
  The command records old and new modes under its owning lock and strict audit.
  An unchanged authorized command is a no-op; legacy owner/admin roles do not grant this action.
- **Launch resolution.** The workspace reservation mutex protects effective-mode resolution (ADR-046-R10). The pinned decision reflects policy at reservation time. The native RAES launch path consumes the pinned verdict.
  CyberScript is retired.
- **Range ownership and replay.** The effective mode is pinned on
  `engine.Range.egress_mode` in the create transaction before dispatch, and an
  idempotent replay that names a different mode is rejected (ADR-017-R5).
- **Transport.** The pinned mode travels in the supported operation input,
  validated against the closed vocabulary. A newer producer always emits it; an
  older queued input without it resolves to `status-quo` (never a silent
  weakening, because `none` is always explicit), and an unknown value fails
  closed at the wire.

### Provider realization

Enforcement uses each cloud's native primitives behind the existing provider
seams; the provisioner never reads workspace state.

- **AWS.** `terraform_vars` maps the pinned mode to the runtime route-table
  bridge: `none` yields no participant default route, NAT, or internet-gateway
  path and no S3 endpoint association; `status-quo` inherits the deployment
  baseline. The deployment-owned `RANGE_EGRESS_MODE` never overrides a pinned
  decision.
- **GCP.** A `none` range-cell forces the firewall egress-deny (no public-web or
  allow-CIDR lane) and, decisively, omits the Cloud NAT entirely: egress is
  range-owned. For non-`none` ranges, the provisioner creates a range-scoped Cloud Router and Cloud NAT (`LIST_OF_SUBNETWORKS`). A `none` range has neither, so its subnet has no NAT path. A firewall deny
  alone is not that guarantee (ADR-026-R6).
- **Backend capability gate.** A `none` launch fails closed on a backend that
  cannot prove native no-NAT support. GDC stays excluded under ADR-030.

### Configuration baseline

A `status-quo` workspace inherits the deployment baseline. That inheritance is
realized at the provider today: the AWS runtime reads the deployment-declared
`RANGE_EGRESS_MODE`, so a deployment-wide `none` posture still reaches a
`status-quo` workspace's ranges. GCP has no deployment-wide `none` baseline (its
operator posture is the allow-CIDR and profile lanes), so a `status-quo` GCP
range keeps the existing routed posture. CMS does not currently normalize the inherited deployment baseline into a concrete mode at reservation. Workspace `none` is fully resolved and pinned. Baseline normalization remains a separate follow-up.

### GCP Cloud NAT migration

The shared range VPC previously enrolled every subnet in one Cloud NAT
(`ALL_SUBNETWORKS_ALL_IP_RANGES`), which is incompatible with a per-range `none`
subnet. It now uses `LIST_OF_SUBNETWORKS` driven by the
`shared_range_nat_subnetwork_self_links` variable (default empty), so in steady
state it enrolls no range subnets and egress is range-owned. The variable is a controlled cutover bridge. During migration, an operator can list existing subnets to preserve egress until they move to per-range NAT. Range jobs never patch this shared object
concurrently. The regional router, NAT, and address quota supporting per-range
NAT is a deployment capacity concern to validate for the declared range count.

## Workspace resource quotas (issue #1946, PLAT-239)

Per-workspace resource quotas are tenant-entitlement policy owned by the
`workspaces` domain, distinct from Engine provider-capacity accounting, API
throttling, billing, and the per-`(user, range_source)` active-range constraint
(ADR-046-R10, `docs/_deprecated/architecture/workspace-resource-quotas-preflight-1946.md`).
The initial closed resources are `concurrent_ranges` and `member_seats`. A
missing policy means unlimited, which preserves prior behavior. Enforcement mode
reuses the `shared.capacity.EnforcementMode` terms only: `advisory` is a soft cap
(warn, record, admit) and `enforcing` is a hard cap (record, block).

### Data model

Three `workspaces` models (migration `0009`):

- `WorkspaceQuotaPolicy` is the configured limit and mode for a
  `(workspace, resource)`, with a `revision` bumped on each change and closed
  vocabulary check constraints.
- `WorkspaceQuotaDecision` is append-only evidence of every configured-policy
  evaluation, pinning the policy limit, mode, revision, usage before the delta,
  outcome, reason code, actor, and correlation key.
- `WorkspaceQuotaReservation` is a durable, idempotent open reservation for
  count-based resources. An open reservation (`released_at` is null) is the
  authoritative concurrent-range usage; the unique
  `(workspace, resource, correlation_key)` constraint makes reserve and release
  idempotent under event redelivery.

### Authoring and read authority

Native quota authoring requires the registered `workspace.manage_quota` action on the exact workspace.
The route is `/api/v1/workspaces/<uuid>/quota-policy/`.
Read-only usage is `/api/v1/workspaces/<uuid>/quota/` and checks `workspace.read`.
`admin_set_workspace_quota_policy` and `admin_workspace_quota_usage` retain the owning service boundary.
Staff, superuser, and legacy roles do not independently grant access.

### Enforcement

- **Member seats.** `WorkspaceMembership` rows are the canonical usage. The seat
  delta is evaluated once in the locked `_insert_workspace_membership`, the single
  insert path shared by direct add and invitation acceptance. Pending invitations
  do not consume a seat; role changes and idempotent re-adds do not re-decide.
- **Concurrent ranges.** The workspace reservation mutex protects evaluation and open reservation in `cms.services._range_launch_common` (`_reserve_active_range_slot`). The pre-minted request UUID supplies the key. An active-range collision or persistence failure rolls back the reservation with the range. The reservation is released only on terminal `FAILED`/`DESTROYED`
  convergence in `cms.handlers.range_events.apply_range_status` (and on immediate
  dispatch failure), never at `DESTROYING` or CMS soft delete. The
  `reconcile_range_events` backstop reuses the same convergent release.

Every enforcement primitive re-acquires the workspace row mutex so its usage count
is race-safe regardless of caller, proven under real PostgreSQL contention in
`tests/workspaces/test_quota_concurrency_postgres.py`. A hard rejection commits decision evidence without committing the denied action. The primitive raises a bounded control-flow signal without writing. After rollback, the caller records the rejection and returns a stable error. A hard
concurrent-range exhaustion is a `409 Conflict` (`WorkspaceLaunchQuotaExceeded`),
distinct from an authorization `403` and a request-rate `429`; a hard seat exhaustion is a
`409` (`workspace_member_seats_exhausted`). A soft-cap overage and every hard-cap
block also emit a strict `shared.audit` `quota_applied` event so the deployment
audit history shows when a cap applied.

### Upgrade backfill

CMS migration `0043` depends on `workspaces/0009`, preserving an acyclic migration graph. It backfills one open reservation per existing non-terminal range projection, including hidden `DESTROYING` rows. A new hard cap therefore counts existing infrastructure. It fails
loudly on inconsistent workspace/request evidence and is idempotent on re-run.
