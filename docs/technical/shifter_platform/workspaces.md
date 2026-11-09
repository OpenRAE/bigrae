# BigRAE Workspaces

Reference for account ancestry, membership, ownership, and resource scope.
The [account administration reference](account-administration.md) describes mounted native APIs.
The [authorization reference](authorization.md) defines permission relationships.

## Account scope introduced by ADR-066

`Account` owns customer resources. Its kinds are `individual`, `team`, and `enterprise`.
An individual account owns resources directly, without an artificial organization or workspace.
Team and enterprise accounts have organizations and workspaces.
New business hierarchies have one default organization and one default workspace per organization.
A default workspace cannot be archived while it remains the default.

`shared.identity_scope.ResourceScope` carries an installation or account scope.
Account scope can include organization and workspace UUIDs.
Owning domains persist scalar ancestry; cross-layer foreign keys remain prohibited.
A membership records association. It does not grant an application action.

## What this domain is for

Workspaces owns SQL hierarchy, membership facts, and the authorization mutation journal.
OpenFGA owns permission relationships.
Services re-resolve exact SQL ancestry before checking policy or changing custody.
An organization is not an identity issuer, cloud project, CTF event, or network boundary.

## Models

| Model | Purpose |
| --- | --- |
| `Account` | Stable customer identity and closed account kind |
| `Organization` | Account subdivision with public UUID and profile |
| `Workspace` | Organization subdivision with public UUID, archive state, and egress policy |
| `AccountMembership` | Principal association with an account |
| `OrganizationMembership`, `WorkspaceMembership` | Principal association with an exact subdivision |
| `WorkspaceOwnership` | Separate principal ownership facts; multiple owners are supported |

Native membership rows use principal UUIDs and an empty legacy role.
Database constraints reject mixed principal and legacy user/role shapes.
Workspace names remain unique within an organization.
Owning services preserve the last-owner and default-workspace invariants under locks.
Internal integer IDs remain internal; public hierarchy routes use UUIDs.

## Service interface

Other layers import `workspaces.services`, rather than models or private implementation modules.
External adapters use the independent SDK rather than this application facade.

| Service family | Purpose |
| --- | --- |
| `hierarchy_target_scope` | Resolve exact persisted ancestry |
| `admin_create_account`, `admin_create_organization`, `admin_create_workspace` | Create an authorized hierarchy |
| `admin_list_accounts`, `admin_list_organizations`, `admin_list_workspaces` | Filter by current policy before counts and pagination |
| `admin_get_account`, `admin_get_organization`, `admin_get_workspace` | Read one authorized scope |
| `admin_rename_workspace`, `admin_archive_workspace`, `admin_restore_workspace` | Apply locked lifecycle commands |
| `policy_transfer_workspace_ownership` | Transfer ownership through native policy and invariant checks |
| `admin_set_workspace_quota_policy`, `admin_set_workspace_egress_policy` | Set policy through current registered actions |

The complete export set is `workspaces/services/__init__.py`.
Use its typed signatures for optional arguments and result projections.
Read [the console reference](org-workspace-admin-console.md) for current routes and fields.

## Role policy and API

Native authorization requires current `CredentialContext`, exact action ceiling, SQL ancestry, and live policy.
A role label, ownership fact, staff flag, or API-token scope alone grants no operation.
Invalid bearer proof cannot fall back to a valid browser session.
Session mutations retain CSRF validation.
Policy-provider failure denies access; it cannot produce a partially authorized page.

`config.account_admin_urls` mounts the native account and membership routes before other includes.
`workspaces.api.account_admin_urls` owns their paths.
Legacy integer-user membership routes and `workspaces/context/` are not the current mounted contract.
Use `/api/v1/accounts/context/` and the principal-UUID membership routes.

## How ranges are scoped

CMS owns desired placement; Engine independently checks and retains realized custody.
Individual-account ranges need no workspace.
Business placement can name an account, organization, or workspace permitted by current policy.
Public callers supply the declared public identities; SQL resolves ancestry.
A malformed or unauthorized selection cannot silently select another scope.

CMS request, range projection, and Engine state must agree on ownership and ancestry.
Scope moves authorize the source and destination independently.
The destination must be live.
A workspace rebind requires the owner's destination-workspace membership; account membership alone is insufficient.

Destination quota admission precedes release of the previous reservation.
CMS and Engine changes commit together with strict audit.
An identical authorized move is a no-op; conflicting projections fail closed.

Membership does not grant SSH, RDP, VPN, Guacamole, or access to another member's range.
Each access path checks the current credential, resource policy, lifecycle, and exact assignment.
Event-owned aggregates and unretired VPN custody prevent independent scope moves.
See [range scoping](range-workspace-scoping-administration.md) and [continuing access](content-range-authority.md).

## Compatibility

ADR-066 retires the personal-workspace authority model through the coordinated S8 cutover.
Historical mapping requires explicit ownership evidence; ambiguous rows block activation.
Legacy role conversion cannot silently add native transfer or administrator permissions.
Historical migration records do not describe supported new authoring or authorization.

## What stays deployment-global

Deployment configuration, provider trust, installed executable bindings, and installation policy remain installation concerns.
The durable audit store remains shared; authorized reads apply native audit policy.
Content can have installation or customer custody through explicit registration.
Private registration does not publish content to other customers.
CTF owns its event and participant facts independently of workspace membership.

## Identity provider integration

Provider adapters first verify issuer, audience, subject, and required assurance.
Management binds that exact provider identity to a native principal.
Provider group claims are not application policy grants or workspace identities.
No automatic claim-to-workspace mapping is documented as supported.
See [unified credentials](access-credentials.md) for the implemented admission contract.
