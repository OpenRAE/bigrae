# Deploy with a coding agent

Use this instruction to install BigRAE on Google Cloud. The agent uses a
published container. It does not need a repository clone.
For the same procedure without an agent, use [Install on Google Cloud](install-gcp.md).
AWS support is coming.

## Prepare the inputs

Complete this table before you start.

| Input | What to provide |
| --- | --- |
| Project ID | A Google Cloud project for this installation, with billing enabled. Use the ID, not its display name. |
| Deployment name | A name of nine characters or fewer, with lowercase letters, numbers, and hyphens. For example, `training`. |
| Hostname | A hostname that you control. For example, `ranges.example.com`. |
| Operator email | The Google account with permission to install in the project. |
| Region | For example, `us-central1`. |
| Zone | A zone in that region. For example, `us-central1-a`. |
| Release tag | A [release](https://github.com/OpenRAE/bigrae/releases) tag such as `vX.Y.Z`, or permission to use the latest release that has a deployer image. Releases v4.1.1 and earlier have no deployer image. |

You must have permission to create the cloud resources and change the hostname's
DNS record. The installation creates billable resources.
The [prerequisites](install-gcp.md#before-you-start) list the tools and project access.
Keep passwords and tokens out of the instruction. Sign in through the tools.

## Give the agent this instruction

Replace each value in angle brackets. Then give the complete text to the agent.

```text
Install BigRAE on Google Cloud with the published release container.

Read and follow this procedure:
https://openrae.github.io/bigrae/getting-started/install-gcp/

Use these inputs:
- Project ID: <project ID>
- Deployment name: <short name>
- Hostname: <hostname>
- Operator email: <Google account email>
- Region: <region>
- Zone: <zone>
- Release tag: <vX.Y.Z, or "latest release that has a deployer image">

Check all prerequisites before you change cloud resources.
Ask me only for missing inputs, authentication, or an action you cannot perform.
Use the release's deployer container. Do not clone or build the repository.
Do not start a release workflow.
Verify the deployer image provenance with cosign, as the procedure shows, before you run it.
Accept only a release build from main at the release tag's source revision.
Keep this installation's files and logs in a private directory.
Select the Google account for each command. Do not change my default account.
Create the two deployment input files described in the procedure.
Use gcp-install for the first installation.
Run long commands in the background and retain their logs.
If a command fails, use its recorded state and the deployment runbook to recover.
Do not delete state, release locks for active work, or bypass a failed check.
When the public IP address exists, provide the exact DNS A record I must create.
Continue work that does not depend on my DNS change.
Finish the certificate, readiness, and range smoke checks.
Do not report success until those checks pass.
Do not destroy an existing installation.
Do not put passwords, tokens, or private keys in messages or source control.

At completion, report the portal URL, project ID, deployment name, release
revision, configuration bucket, and checks that passed.
Give me the command to retrieve the initial operator password privately.
Explain how to sign in, set up an authenticator, update, and remove the installation.
State any remaining action or failed check explicitly.
```

## Complete the steps that need you

1. Complete the Google browser sign-ins when the tools request them.
2. When the agent provides a public IP address, add the requested DNS A record.
3. If your DNS provider has a proxy option, turn the proxy off for this record.
4. Open the portal after its certificate is active.
5. Retrieve the initial password with the command the agent provides.
6. Sign in and set up an authenticator when the portal requests it.

The first install can return before the certificate is active. The agent must
run the completion step after DNS resolves. An unfinished certificate is not a
completed installation.

## Keep the installation record

Keep the configuration directory, release image address, source revision,
configuration bucket name, and logs. You need them for updates and recovery.
Keep credential values in their existing credential stores.
