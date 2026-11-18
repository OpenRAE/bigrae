# Security

Use this how-to guide to report a suspected BigRAE vulnerability privately.
Choose one of these channels:

- GitHub private vulnerability reporting: open the
  [vulnerability report form](https://github.com/OpenRAE/bigrae/security/advisories/new).
- Email to the repository maintainer, Brad Edwards, at
  [brad@autarchy.ai](mailto:brad@autarchy.ai).

Do not report vulnerability details through public issues or pull requests.
The maintainer manages the BigRAE security response on a best-effort basis.
There is no guaranteed response or remediation deadline.

1. Include the affected release or commit and a concise impact summary.
2. Include a synthetic reproduction when possible.
3. Omit credentials, customer or private scenario data, signed URLs, and operational logs.
4. Arrange an appropriate private channel with the maintainer before sending sensitive supporting material.

Use the current integration branch and review release-specific limitations in
[the handbook](docs/technical/architecture.md). No supported-version matrix or
independent security certification is claimed.
Coordinate disclosure with the maintainer after triage.
Vulnerabilities in third-party products should also
follow the affected vendor's reporting policy.
