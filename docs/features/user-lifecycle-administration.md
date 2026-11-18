# User lifecycle administration

Manage human accounts through **Administer > Platform > Users**.
You need current `installation.manage_principals` authority and the matching credential ceiling.
The server rechecks authority for each request.
A staff flag or legacy Django model permission alone does not supply it.

## Access

1. Open **Administer > Platform**.
2. Open **Users**.
3. Use **Search users** to find the account.
4. Select the user.
5. Check its principal UUID and lifecycle state before an action.

Select **Include deleted users** when a soft-deleted account must be inspected.
The page shows actions applicable to that account; each request still requires authorization.

## Account states

| State | Meaning |
| --- | --- |
| Active | The account can sign in when its other identity checks pass. |
| Suspended | Sign-in is blocked temporarily; assignments and resources remain. |
| Deactivated | Sign-in is blocked for reversible offboarding. |
| Deleted | The account is soft-deleted and excluded from the default list. |

Select the required state action and **Confirm identity change**.
Suspension, deactivation, and deletion invalidate sessions and revoke live API tokens.
Reactivation restores sign-in eligibility, not revoked tokens.
Self-lockout and last-active-superuser protections remain enforced.
Soft deletion does not permanently erase or anonymize the account.

## Password reset

Select **Reset password**, then **Confirm identity change**, for an eligible local account.
The platform emails a reset link and reports the delivery result.
It never displays that link in the interface.
A configured mail provider is required.
Provider-bound accounts reset credentials at their identity provider.
Temporary event accounts use the separate participant password flow.

Only the account owner's browser session can change that account's recovery email.
Another administrator can request a reset and edit other permitted profile metadata.

## Transfer ownership

Use offboarding when a departing user's eligible resources need another owner.
The replacement must satisfy each resource's membership and authority checks.

1. Open the departing user's detail.
2. Enter **Replacement user ID**.
3. Select the resource kinds to transfer.
4. Review the transfer and confirm it.
5. Inspect both successful and blocked counts.

Transferred ranges keep their workspace scope.
A range with a live participant VPN credential is blocked; use the approved destruction and replacement procedure.
Workspace transfer requires an existing eligible member and excludes personal workspaces.
Blocked resources are not silently reassigned.
The transfer does not move stored installers, source credentials, or historical actor records.

## What these actions do not do

Lifecycle administration does not delete an external identity-provider account.
It does not recall a downloaded credential or prove cloud cleanup.
Ongoing remote access follows the [continuing-access contract](content-range-authority.md).
See [account administration reference](../technical/shifter_platform/account-administration.md) for exact request and permission rules.
