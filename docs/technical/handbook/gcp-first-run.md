# First sign-in and first range

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

For a failure, use the [deployment runbook](../../runbooks/rb023-gcp-deployment.md).
An active web page alone does not prove that range provisioning works.

## Run the first range

The installation registers its initial catalog through the application's content service.
The synthetic `smoke-linux` pack provides a small initial GCP range.
It is an installation check, not a complete scenario catalog.

1. Open the range list in the portal.
2. Select an available scenario. For the initial check, use `smoke-linux`.
3. Read its input and access requirements.
4. Submit the launch request in an account or workspace where you have launch permission.
5. Wait until the range reports `Ready`.
6. Open its terminal or other declared access channel.
7. Run a simple command in the guest, such as `hostname`.
8. Confirm that the guest returns a result.
9. Destroy the range through the portal.
10. Confirm that teardown completed without residual resources.

If the scenario is unavailable, ask the installation administrator to check
catalog registration and its cloud image mappings. Do not select an unrelated
scenario as evidence that the missing scenario works.

## Add other scenarios

Use the [pack and adapter procedure](../../ops/artifact-preparation.md).
An administrator must install and bind executable adapters separately from pack data.
Follow each pack's instructions for its files, credentials, images, and cloud permissions.

A deployment smoke check does not qualify a custom scenario.
Before participants use it, test its setup, access, expected actions, and teardown.
