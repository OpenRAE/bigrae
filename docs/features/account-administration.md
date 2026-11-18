# Account administration

Use **Administer > Accounts** to administer the account scopes permitted by current policy.
This guide follows the mounted source interface.
It does not establish live-cloud or published-release qualification.

## Select an account or scope

1. Open **Administer > Accounts**.
2. For an individual account, use the account view that opens directly.
3. If **Other accounts** is available, select it to browse permitted accounts.
4. Use **Search accounts** to find a permitted account.
5. Select its name.

Individual accounts own resources without synthetic organization or workspace selectors.
Team and enterprise accounts contain real organizations and workspaces.
A directly permitted descendant can appear under **Your organizations and workspaces**.
Select it there when you cannot read its parent account.

## Create a subdivision

You need the corresponding account or organization administration action.
Membership, ownership, staff status, and cloud IAM alone do not supply that permission.

1. Select the parent account or organization.
2. Enter the new name in the appropriate creation form.
3. Select the creation action.
4. Read the result before submitting another command.

If access setup is pending, select **Retry access setup**.
The retry resumes the same object's recorded publication.
Do not create a second object to recover the first.

## Administer the selected scope

Use the scope's member and policy tabs separately.
Adding membership records who belongs there; it does not assign permissions.
See [workspace administration](org-workspace-admin-console.md) and [policies and groups](authorization-policies-and-groups.md).

For user state, password reset, or offboarding, use [user lifecycle administration](user-lifecycle-administration.md).
Only an account owner can change their own recovery email through their browser session.
Administrators can edit other permitted profile metadata and request password resets.

## Reference and explanation

The [account administration reference](../technical/shifter_platform/account-administration.md) defines exact API and authority contracts.
[Key concepts](../getting-started/concepts.md) explains scopes, ownership, and permissions.
