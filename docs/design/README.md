# Design explanations and references

Designs describe a decision, proposal, or implementation boundary.
Their status and evidence limits apply even when source code exists.
An approved design does not establish production activation or live qualification.

## Current design routes

| Subject | Explanation and applicability |
| --- | --- |
| Identity | [Integrated identity cutover](identity-cutover-2321-proposal.md) records S8 approval, integration corrections, and verification limits |
| Provider identity | [AWS integration](aws-native-identity-integration-2313.md) and [GCP integration](gcp-native-identity-integration-2320.md) state their provider-specific evidence limits |
| Content and range authority | [Authority proposal](content-range-authority-2319-proposal.md) and [gateway revalidation](guacamole-gateway-revalidation-2319-proposal.md) describe the approved boundaries |
| Communications | [Console boundaries](ctf-communications-console-boundaries-2052.md) and [participant inbox](ctf-participant-inbox-boundaries-2053.md) specialize the communication design |
| Email | [Ledger templates](ctf-ledger-email-template-boundaries-580.md) and [recipient time zones](ctf-recipient-time-zone-582.md) record accepted design constraints |
| Scoreboards | [Refresh design](ctf-scoreboard-refresh-576.md) explains the 30-second update boundary |
| Visual examples | [Design-system artifacts](design-system/README.md) describe the HTML/CSS reference examples and their limits |
| UX research | [Research personas](ux-003-oss-shifter-research-personas.md) and [information architecture](ux-003-information-architecture-sitemap.md) retain their dated research context |

The [ADR registry](../adr/README.md) records governing decisions and supersession.
The [current architecture](../technical/architecture.md) describes the implemented system.
The [subsystem references](../technical/shifter_platform/index.md) describe current contracts.

## Preflights and evidence

Preflights record constraints for an issue at its review baseline.
An accepted ADR can retain those constraints after implementation.
The filename alone does not determine whether a decision still applies.
Follow the document's status, amendments, and governing ADR before using it.

Dates, research results, approval quotations, and original verification outputs remain source-bound evidence.
They do not become current operating instructions through a prose change.
Executable examples retain their exact contracts.
