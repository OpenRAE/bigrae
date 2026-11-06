# First sign-in

Start after the installation checks have passed.
For a new environment, first complete [Install on Google Cloud](../../getting-started/install-gcp.md).

## Sign in

1. Open the portal's HTTPS URL in a browser.
2. Use the administrator email from the installation configuration.
3. Retrieve the initial password from Secret Manager with the
   [password command](../../getting-started/install-gcp.md#9-sign-in).
4. Enter the password in the portal. Keep it out of messages and logs.
5. Follow the portal's instructions to set up an authenticator.
6. Complete the second-factor sign-in.

For an existing installation, use the account and access that its administrator provides.
The initial administrator password belongs only to the initial account.

## Check the installation

Before you launch a range, confirm these results:

- The hostname resolves to the installation's ingress IP.
- The browser accepts the HTTPS certificate without an exception.
- The deployment reported that its running images match the selected release.
- The configured post-deploy smoke passed and was not skipped.

An active web page alone does not prove that range provisioning works.

## Launch the first range

The in-box catalog holds the synthetic `smoke-linux` scenario: a Kali attacker
and an Ubuntu victim. It is an installation check, not a complete scenario
catalog. To launch it, connect to it, and destroy it, follow
[Launch your first range](../../getting-started/quickstart.md).

If the scenario is unavailable, ask the installation administrator to check
catalog registration and its cloud image mappings. Do not select an unrelated
scenario as evidence that the missing scenario works.

## Add other scenarios

Use the [pack and adapter procedure](../../ops/artifact-preparation.md).
An administrator must install and bind executable adapters separately from pack data.
Follow each pack's instructions for its files, credentials, images, and cloud permissions.

A deployment smoke check does not qualify a custom scenario.
Before participants use it, test its setup, access, expected actions, and teardown.

## When something fails

- [RB023](../../runbooks/rb023-gcp-deployment.md) lists the failure symptoms
  and the fix for each deploy stage.
- [GCP tenant standup gotchas](../../dev/gcp-tenant-standup-gotchas.md) lists
  known problems and their fixes.
