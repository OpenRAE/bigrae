# Authorization policies and groups

Use this guide to assign scoped permissions through the account administration surface.
You need authority to administer authorization for the selected scope.
Your credential ceiling must permit each delegated action too.

## Concepts

A **group** collects human or service principals by public principal UUID.
A **policy** collects explicit BigRAE actions.
A **policy assignment** attaches a policy to a principal or group.
A **direct assignment** grants one action to a principal or group.
Predefined administrator policies provide reusable action sets and matching groups.
Membership and ownership remain separate from those permissions.

## Grant or revoke authority

1. Open **Administer > Accounts**.
2. Select the permitted account, organization, or workspace.
3. Open its policy tab.
4. Select the principal or group and the explicit policy or action.
5. Review the target scope before submitting the change.
6. Inspect the returned operation state.

| State | Meaning |
| --- | --- |
| `requested` | The intent is recorded and is being applied. |
| `confirmed` | Authoritative OpenFGA readback matches the requested state. |
| `denied` | The actor, credential, or scope cannot delegate that authority. |
| `unresolved` | The external outcome is uncertain. |

HTTP acceptance alone does not prove that permissions changed.
For `requested` or `unresolved`, use **Reconcile status** to retry authoritative readback.
A status refresh observes the operation; it does not repeat the mutation.

If the response was lost before an operation ID arrived, use **Retry original command**.
The page preserves the original destination, payload, and retry key.
Do not edit those inputs or submit a different command until the original result is known.

## Safety rules

The server rejects delegation beyond current authority or credential limits.
It rejects self-add, cross-account references, unknown actions, invalid ancestry, and unavailable evaluators.
Revocation establishes an exclusion before removing the positive relationship.
Delayed older work cannot restore a completed revocation.
See [authorization reference](../technical/shifter_platform/authorization.md) for exact contracts.
