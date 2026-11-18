# Development

This section is for source changes. To install BigRAE, use
[Install on Google Cloud](../../getting-started/install-gcp.md).
The local contribution route does not require a cloud deployment.

## Set up development

- [Local development setup](local-setup.md): run the portal and targeted checks
- [Developer environment setup](setup.md): deploy a development environment
  from your own fork with GitHub Actions on the selectable `aws-dev` target
- [Configuration schema](installation-config.md)
- [Test commands](../../dev/testing.md)
- [Architecture rules](adr-enforcement.md)

Use the Python and frontend versions declared by the package that you change.
Submit source changes to `dev`. Follow the repository's contribution instructions.

## Reference

- [Platform API development](api.md)
- [Cloud adapters](cloud-adapters.md)
- [Terraform](terraform.md)
- [CI/CD](ci-cd.md)
- [Secrets](secrets.md)
- [Privacy notice](privacy-notice.md)
- [Development principles](principles.md)

## Submit and qualify a change

- [Contribution and documentation workflow](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md)
- [Development and release workflow](../../DEVELOPMENT_WORKFLOW.md)
- [QA protocols](../../qa/index.md): authorized live qualification and its limits
- [Support](../../reference/support.md): ordinary defects and private security reporting
