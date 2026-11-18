# Range-to-workspace scoping administration (technical)

This reference describes range-to-workspace scoping administration (PLAT-237, issue #1944). It covers the scoped range query and the command that changes workspace scope. It is constrained by PLAT-241 (cloud-agnostic, proven components) and the
architecture preflight at
`docs/_deprecated/architecture/range-workspace-scoping-administration-preflight-1944.md`.

## What is administered

A range's workspace binding is the scalar `workspace_id` copied from CMS request
intent to the CMS range projection and the Engine range. It is a soft reference,
not a cross-layer ForeignKey (ADR-001-R2, ADR-046). This feature administers that
one fact. It never changes the range owner, source, lifecycle, lease, or access.

## Authority

Native scope administration uses current credentials, action ceilings, and SQL-owned ancestry.
`PolicyWorkspaceRangeScopeListView` calls `policy_list_range_scope_bindings`.
`PolicyRangeWorkspaceRebindView` calls `policy_rebind_range_workspace`.
Both services are exported through `cms.services`.
The owning Workspaces service authorizes the source and destination before mutation.
Legacy owner/admin roles and staff flags are not the current authority boundary.

The API accepts admitted bearer credentials or current browser sessions.
Browser mutations require CSRF. Invalid bearer proof fails before session fallback.
The destination must be live.
The retained owner needs destination-workspace membership; account membership alone is insufficient.

Current local proof and expected ancestry are checked again under the owning locks.
Unavailable policy cannot authorize a partial move.

## Service and persistence boundary

CMS owns request intent, the range projection, and both administration operations. ADR-001 permits CMS to compose `engine.services` and `workspaces.services`. The seam lives in
`cms/services/_policy_range_scope.py`.

`policy_list_range_scope_bindings(actor, provider, *, workspace_uuid)` authorizes the current credential on the exact workspace and returns an ordered queryset of
its range projections for the API to paginate. An explicit DRF serializer exposes request UUID, owner ID, source, status, scenario, timestamps, and derived `is_reassignable`. It is not a `ModelSerializer`. It exposes no internal ID, range specification, address, credential, or ORM object.

`policy_rebind_range_workspace(actor, provider, *, request_id, target_workspace_uuid, audit)` runs
policy admission before a `transaction.atomic` block.
The operation:

1. locks and uniquely resolves the CMS Request and its one RangeInstance and
   confirms they carry the same expected source scope;
2. fails closed for a range that is not Mission Control sourced (see below);
3. prepares current source and destination policy with `authorize_policy_range_rebind`. The locked commit checks that admitted ancestry is unchanged;
4. calls `engine.services.rebind_range_workspace_by_request` with expected-source
   compare-and-set semantics; and
5. moves CMS projections and quota reservation to the target. It writes a strict request-attributed `shared.audit` event with internal IDs and old/new scope. Any failure rolls back the transaction.

Moving to the current consistent binding is an authorized idempotent no-op that
writes no mutation audit. Missing, duplicate, or disagreeing projections return a bounded conflict. Concurrent moves and unexpected Engine bindings also conflict. The command does not silently repair or overwrite them.

## Engine compare-and-set

`engine.services.rebind_range_workspace_by_request` was changed from an
unconditional bulk update to an expected-source compare-and-set. It takes a row
lock, resolves exactly one Engine range for the request, and returns a
`RangeWorkspaceRebindOutcome` (`UPDATED`, `UNCHANGED`, `NOT_FOUND`, or
`SOURCE_MISMATCH`); a duplicate projection raises `RangeProjectionIntegrityError`.
The Engine still never resolves or authorizes a workspace (ADR-046-R1). The owner-rehome path in `cms/services/_range_reassign.py` supplies the expected current binding. A non-success outcome rolls back that path.

## Domain-owned aggregates fail closed

A range that belongs to an immutable domain-owned workspace aggregate, such as an
ADR-051 capture-the-flag event, cannot be moved independently. CMS cannot import `ctf` to validate aggregate membership. The scalar `range_source` label is not aggregate membership. The shared aggregate boundary detects retained domain ownership. Following ADR-046-R14, the command
administers Mission Control ranges only and refuses any other range with a bounded
outcome. The shared aggregate check does not authorize an independent event-range move.

## API surface

Both routes live under the CMS API at `/api/v1/cms/`:

- `GET workspaces/<uuid:workspace_uuid>/range-scoping/` lists the ranges scoped to
  a workspace, paginated. An unknown or unauthorized workspace returns one opaque
  404.
- `POST ranges/<uuid:request_id>/scope/` reassigns a range's scope. The body
  is a closed `{ "target_workspace_uuid": "<uuid>" }`. The classified
  `RangeScopeAdminError` maps to a bounded status: 404 when the range is absent or its source cannot be administered. Target-ineligible, conflict, and not-reassignable outcomes return an opaque 409. A malformed target
  UUID is a 400 at the serializer.

The committed OpenAPI contract (`openapi/v1.json`) and the generated frontend
types (`frontend/src/api/schema.d.ts`) are regenerated with `npm run gen:api`.

## SPA surface

The `range-scoping` console slot renders
`frontend/src/features/administer/organization/WorkspaceRangeScopingPage.tsx`. It
lists the ranges through the `frontend/src/api/rangeScoping.ts` TanStack Query
hooks and offers a reassignment dialog whose target options are the workspaces the
caller administers. The SPA uses server-derived action hints and public UUIDs. It does not reconstruct role policy. The server reauthorizes each command and checks target state and owner eligibility.

## Cloud neutrality

Reassignment is a database control-plane action. It reads and writes no secret and dispatches no provider work. The move does not re-evaluate pinned egress or provider placement. Destination workspace quota is checked.
