# Installation setup

## Before you start

The current installation path uses a published Google Cloud release container.
It does not require a repository clone or a development toolchain.

- [Deploy with a coding agent](../../getting-started/deploy-with-agent.md)
- [Install step by step](../../getting-started/install-gcp.md)

## GCP deployment

Follow [Install on Google Cloud](../../getting-started/install-gcp.md).
That guide owns the prerequisites and the complete installation procedure.
It includes project access, billing, tools, release verification, the two input
files, DNS, the initial administrator, updates, and removal.

Use the [deployment reference](../handbook/gcp-github-less-deployment.md)
for advanced settings and individual commands.
Use [RB023](../../runbooks/rb023-gcp-deployment.md) for a failed operation.

## AWS deployment

AWS support is coming. The older development deployment is not the user installation path.

## Root installation config

A deployment uses `bigrae.yaml` and `terraform.tfvars.json` in a private input directory.
The installer stores those inputs in the deployment configuration bucket.
The [installation guide](../../getting-started/install-gcp.md#4-create-the-two-input-files)
provides complete file contents.
The [configuration reference](installation-config.md) describes additional settings.

## Local development

To change the source code, use [Local development setup](local-setup.md).
The development environment and its test tools are separate from the release installation procedure.
