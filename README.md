# BigRAE

Self-service agentic cyber-range platform for authorized purple, red and blue
team exercises, with isolated guest workloads and operator-selected telemetry.
Canonical repository: [OpenRAE/bigrae](https://github.com/OpenRAE/bigrae).

Documentation: [openrae.github.io/bigrae](https://openrae.github.io/bigrae/).

## Install

The GCP installation route uses a verified release container.
It needs no GitHub account, fork, or repository checkout.
The latest published release checked on 2026-11-09, `v4.1.1`, predates the deployer image.
Select an eligible later release before using the current installation procedure.
Current GCP and AWS backend source does not establish published-release support.

1. Select a release (see [Releases](#releases)).
2. Follow [Install on Google Cloud](docs/getting-started/install-gcp.md).
   You need a GCP project with billing on, a domain that you control, Docker,
   the `gcloud` CLI, Git, ORAS, and cosign.
3. [Launch your first range](docs/getting-started/quickstart.md).

## Releases

A release is a [GitHub release](https://github.com/OpenRAE/bigrae/releases)
`vX.Y.Z` of `main`. The GCP release workflow publishes these images to the public registry
`ghcr.io/openrae/bigrae`, with signed build provenance:

- the deployer image `deployer-gcp`, which holds the install commands, the
  Terraform roots, the Helm chart, and the pinned tools;
- the control-plane images `portal`, `provisioner`, `guacd`,
  `guacamole-client`, and `openvpn`.

Each image tag is the full commit SHA of the release, not the version. Releases
v4.1.1 and earlier have no deployer image. [CHANGELOG.md](CHANGELOG.md) lists
the changes in each release.

## Documentation

| Purpose | Start here |
| --- | --- |
| Tutorials | [Launch your first range](docs/getting-started/quickstart.md) on an installed GCP tenant. |
| How-to guides | [Feature tasks](docs/features/index.md) and [troubleshooting](docs/how-to/troubleshooting.md). |
| Reference | [FAQ](docs/reference/faq.md) and [technical contracts](docs/technical/shifter_platform/index.md). |
| Explanation | [Key concepts](docs/getting-started/concepts.md) and [architecture handbook](docs/technical/architecture.md). |

[Get started](docs/getting-started/index.md) links the installation and learning routes.
The [GCP deployment guide](docs/technical/handbook/gcp-github-less-deployment.md) owns full operator procedures.
The [documentation site](https://openrae.github.io/bigrae/) publishes `docs/` from `main` under ADR-038.

## Develop

Use Python 3.12+, [uv](https://github.com/astral-sh/uv), the frontend's declared
Node version and npm, and [pre-commit](https://pre-commit.com/). The platform
and packer packages require Python 3.14.
From the repository root:

```shell
uv sync --project shifter/shifter_platform
uv sync --project shifter/installation
npm ci --prefix shifter/shifter_platform/frontend
pre-commit install
```

Use [local development setup](docs/technical/dev/local-setup.md) and
[contribution guidance](CONTRIBUTING.md) for the development workflow.
To deploy a development environment from your own fork with GitHub Actions,
on AWS or GCP, see [developer environment setup](docs/technical/dev/setup.md).

## Test and document

Run tests for the packages you change, for example:

```shell
make test-platform
make test-provisioner
make policy
uv run --with-requirements docs/requirements.txt mkdocs build --strict
```

The [command matrix](docs/dev/testing.md#command-matrix) lists every lane and
its CI job. See also [ADR enforcement](docs/technical/dev/adr-enforcement.md).
CI owns the full quality matrix; local hooks also enforce architecture and
secret hygiene. Architecture-boundary changes include handbook review.

## Support and security

BigRAE is maintained on a community, best-effort basis without a response SLA.
Use [SUPPORT.md](SUPPORT.md) for assistance and support limits and
[SECURITY.md](SECURITY.md) for private vulnerability reporting. Run exercises
only in environments you are authorized to control, with human oversight.

The maintainer is [Brad Edwards](https://github.com/Brad-Edwards). The repository
is MIT licensed; [LICENSE](LICENSE) retains the copyright holders' notices.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Feature PRs target `dev` and use
Conventional Commit titles. Release Please owns the version and `CHANGELOG.md`
from the history promoted to `main`; see
[the release workflow](docs/DEVELOPMENT_WORKFLOW.md).

## Repository history

The repository was renamed on 2026-10-25 and moved to the `OpenRAE`
organization on 2026-10-29. Old repository URLs redirect to `OpenRAE/bigrae`.
GitHub Pages does not redirect the old documentation site paths, so update
bookmarks.

## Citation

```bibtex
@software{shifter,
  author       = {Edwards, Brad},
  title        = {Shifter: Self-Service Agentic Cyber Range Platform},
  year         = {2026},
  license      = {MIT},
  url          = {https://github.com/OpenRAE/bigrae}
}
```

Include the exact release or commit you used in your publication.
