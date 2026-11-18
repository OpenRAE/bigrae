# Workspace membership

Manage membership in a workspace that you are authorized to administer.
Membership records who belongs to a scope.
Policies separately authorize application actions.

## Roles

The mounted account interface uses human and service principal memberships.
The historical owner/admin/member table is not its current permission contract.
Owners are recorded separately, and ownership alone grants no permission.
A workspace must retain an owner.
See [policies and groups](authorization-policies-and-groups.md).

## Manage membership with the API

Use the [account administration reference](../technical/shifter_platform/account-administration.md) for exact routes and request fields.
The current member form accepts a public principal UUID rather than an internal database identifier or email.
Browser writes use the existing session and CSRF protection.
A native credential must also permit the requested action and scope.

To use the portal:

1. Open **Administer > Accounts**.
2. Select the workspace or a directly permitted workspace entry.
3. Open **Workspace members**.
4. Enter **Member principal UUID**.
5. Select **Add member**.
6. Check that the membership appears.

To remove membership, select the principal and then **Confirm removal**.
Removal does not delete the principal.
Required cleanup and range expiry retain their own authority.
For ongoing access and revocation, see [continuing access](content-range-authority.md).

## Invite a new member

1. Open **Invitations** for the selected workspace.
2. Enter the recipient's email.
3. Select **Send invitation**.
4. Read the invitation and delivery status.

The recipient must accept through their freshly verified provider identity.
The signed invitation is delivered through email, not returned in the list.
Resending rotates the credential; revocation invalidates it.
Acceptance adds membership without silently changing an existing membership or assigning permissions.
See the [invitation reference](../technical/shifter_platform/workspace-member-invitations.md).

## Launch a range in a workspace

Select the authorized workspace before choosing a scenario in **Launch a range**.
The scenario and installer choices refresh for that scope.
An unavailable workspace is refused rather than replaced silently.
Workspace membership alone does not let you open, change, or destroy another principal's range.
See [range operations](ranges.md).
