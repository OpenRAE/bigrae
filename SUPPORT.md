# Support

Use this how-to guide to request help with BigRAE.
Assistance is best effort. There is no guaranteed response time, availability, managed operations service, or release-support period.
BigRAE is community maintained and provided as-is under the [MIT license](LICENSE).
Product vendors' support contracts do not cover BigRAE installations, scenarios, or integrations.

## Find the correct route

1. Check the [current-state handbook](docs/technical/architecture.md) for support limits.
2. Use [Install on Google Cloud](docs/getting-started/install-gcp.md) for installation.
3. Use [local setup](docs/technical/dev/local-setup.md) for source development.
4. Ask your deployment operator about deployment accounts and access.
5. Follow [SECURITY.md](SECURITY.md) for suspected vulnerabilities.

The selected backend, exact artifacts, and live qualification determine support.
Source code or a passing compatibility probe does not qualify a scenario.

## Report an ordinary defect

1. Open a non-sensitive report in the [canonical issue tracker](https://github.com/OpenRAE/bigrae/issues).
2. Include the release or commit, selected backend, expected behavior, and actual behavior.
3. Include a synthetic reproduction when possible.
4. Remove credentials, signed URLs, private pack identities, customer configuration, and operational evidence before posting.

Keep private scenario evidence in its owning repository.
Do not post vulnerability details in public issues or pull requests.
If the report needs sensitive evidence, arrange a private channel through the security policy first.
