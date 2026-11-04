# BigRAE

Install and operate cyber ranges on Google Cloud.

## Install

Use the published release container. It contains the installer and its tools.
You do not need to clone this repository or install a development environment.

- [Deploy with a coding agent](docs/getting-started/deploy-with-agent.md):
  required inputs and a complete instruction to give the agent.
- [Install step by step](docs/getting-started/install-gcp.md): prerequisites,
  permissions, release verification, configuration, DNS, and first sign-in.
- [Update or remove an installation](docs/getting-started/install-gcp.md#update-an-installation).

The current installation path uses Google Cloud. AWS support is coming.
The older AWS development deployment is not the user installation procedure.

## Use an installation

Open the installation's hostname in a browser. Sign in with the account that
its administrator provides. Use
[first sign-in and first range](docs/technical/handbook/gcp-first-run.md)
to check access and run a scenario. Scenario inputs depend on the selected pack.

## Documentation

Read the [documentation site](https://openrae.github.io/bigrae/).
For an installation failure, use the
[GCP deployment runbook](docs/runbooks/rb023-gcp-deployment.md).
The [deployment reference](docs/technical/handbook/gcp-github-less-deployment.md)
contains the command and configuration details.

## Develop

Source changes require a repository checkout. Use the
[local development setup](docs/technical/dev/local-setup.md),
[contribution guide](CONTRIBUTING.md), and
[test command matrix](docs/dev/testing.md#command-matrix).
Submit pull requests to `dev`.

## Support and license

- [Support](SUPPORT.md)
- [Report a security vulnerability](SECURITY.md)
- [MIT license](LICENSE)
