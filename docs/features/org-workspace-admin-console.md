# Organization/workspace admin console

Manage organizations and workspaces through **Administer > Accounts**.
The old `/administer/organization/` route redirects to the account surface.
Use [account administration](account-administration.md) to select an account or directly permitted scope.

## Access

Current application policy and credential limits authorize each operation.
A staff flag or workspace membership alone does not grant administration.
The server checks every request, including a request from an otherwise visible control.
The policy-aware Django admin remains available for permitted administration tasks.

## Working in the console

Select an account, organization, and workspace that you may administer.
Use the matching tab for members, invitations, ownership, quotas, or policies.
A forbidden scope is an access failure, not proof that the scope is empty.
If a creation reports pending access setup, use **Retry access setup** for that object.

## Organization settings

1. Select the organization.
2. Change the permitted name, description, support email, or support URL.
3. Select **Save organization**.
4. Correct any field error before retrying.

Only changed fields are submitted.
An empty value clears a field when the contract permits it.
This form does not manage logos.

## Workspaces

1. Select the organization's **Workspaces** tab.
2. Use **Search workspaces** to find a name.
3. Select **Include archived workspaces** when needed.
4. Select the workspace to open its controls.

To create one, enter a unique name and select **Create workspace**.
To rename one, use **Workspace name** and **Rename workspace**.
For archival or restoration, select the lifecycle action and confirm it.
Default workspaces cannot be archived.
Archival retains bound ranges; it does not destroy them.

## Membership and roles

Use **Workspace members** to manage membership by principal UUID.
Use **Workspace policies** to assign permissions separately.
The mounted account interface does not use the retired owner/admin/member role table as its permission model.
See [membership tasks](workspaces.md).

Under **Ownership**, select an existing owner and an active member as the destination.
Select **Transfer ownership**, then **Confirm ownership transfer**.
Use **Add owner** when another owner should remain alongside the current owners.
The last owner cannot be removed.
Ownership itself grants no application permission.

## Invite and onboard members

1. Open **Invitations** in the selected workspace.
2. Enter **Recipient email**.
3. Select **Send invitation**.
4. Read both invitation state and email delivery state.

The recipient must accept with a fresh, provider-verified identity for that email.
Acceptance adds membership without granting permissions.
**Email accepted** means the mail provider accepted the message; it does not prove that the recipient read it.

Use **Resend invitation** for a new link and expiry.
Resending invalidates earlier links.
Use **Revoke invitation**, then **Confirm revocation**, to stop acceptance.
The list never returns the signed credential.

## Network egress policy

You need permission to manage egress for the selected workspace.

1. Open **Quota and egress**.
2. Select **Inherit deployment policy** or **Zero outbound egress**.
3. Select **Save egress**.

The change applies to newly provisioned ranges.
It does not change running ranges or their current network paths.
The backend implements the permitted network posture; ask the operator to verify it for your deployment.

## Resource quotas and usage

You need quota-read authority to inspect usage and quota-management authority to change a limit.
The current surface supports **Member seats** and **Concurrent ranges**.

1. Open **Quota and egress**.
2. Inspect usage and the current limit.
3. Select **Quota resource**.
4. Select **Enforce limit** or **Warn only**.
5. Enter the nonnegative integer **Quota limit**.
6. Select **Save quota**.

An enforcing limit blocks an over-limit action.
An advisory limit records the overage while allowing the action.
An unconfigured limit appears as unlimited.
Lowering a limit does not evict members or destroy running ranges.

## What is not here yet

This guide describes the current mounted account surface, not a release roadmap.
Use [user lifecycle](user-lifecycle-administration.md), [range scoping](range-workspace-scoping-administration.md), and [audit](admin-audit-activity.md) for their current tasks.
The [technical reference](../technical/shifter_platform/account-administration.md) defines exact contracts and failure behavior.
