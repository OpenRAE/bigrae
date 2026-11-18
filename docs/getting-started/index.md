# Get started

Use an existing BigRAE deployment for authorized range exercises.
Ask its operator for the portal address, your account, and the permitted workspace.

## Install or join a deployment

[Install on Google Cloud](install-gcp.md) is the operator-owned installation route.
It requires a published release with a verified GCP deployer image.
As checked on 2026-11-09, the latest published release, `v4.1.1`, has no deployer image.
Do not use that release with the current installation commands.
See [release selection](install-gcp.md#3-select-and-verify-a-release) before you proceed.

The current source includes GCP and AWS backends.
Source availability does not establish a supported release installation or a qualified tenant.
[Contributor deployments](../technical/dev/setup.md) have a separate setup procedure.

## Tutorials

[Launch your first range](quickstart.md) uses an installed GCP tenant.
You will launch the public Linux smoke scenario, inspect both guests, and remove the range.

## How-to guides

Use the [feature guides](../features/index.md) for range, terminal, account, and CTF tasks.
Use [troubleshooting](../how-to/troubleshooting.md) when a task fails.

## Reference

Use the [FAQ](../reference/faq.md) for common limits and capability questions.
The [technical reference](../technical/shifter_platform/index.md) gives exact contracts.

## Explanation

Read [key concepts](concepts.md) for the relationships between releases, scenarios, agents, and ranges.
