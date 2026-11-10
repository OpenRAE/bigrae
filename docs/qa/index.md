# QA and validation

Choose a protocol for the behavior you need to verify.
These how-to guides require authority to use the selected tenant and test actors.
Source tests and a successful deployment do not prove every participant journey.

## Protocols

- [Native CTF smoke and validation](native-ctf-smoketest.md): organizer and participant tasks, scoring, isolation, lifecycle, and regression checks.
- [Range functional smoke](range-functional-smoke.md): real terminal exchange and a Guacamole client session against an existing ready range.
- [GCP event capacity gate](../ops/gcp-event-capacity.md): the selected capacity profile's participant count, continuous session hold, and provider health budgets.

The capacity profile determines the participant count; do not assume every profile uses 30 participants.
A normal browser login can require interactive MFA.
The functional smoke harness also supports an operator-provisioned Identity Platform credential with enrolled TOTP.
Neither route bypasses authentication.

## Before live qualification

1. Select the protocol and exact deployment revision.
2. Obtain operator authority for its effects and workload.
3. Prepare synthetic actors and the required known state.
4. Follow the protocol's safety, success, failure, and cleanup steps.
5. Keep credentials and private operational evidence out of public reports.

Use the [testing reference](../dev/testing.md) for targeted source checks and CI ownership.
Use the [UAT entry](https://github.com/OpenRAE/bigrae/blob/dev/uat/README.md) for harness sources and preserved scenario-editor records.
External packs retain their scenario acceptance evidence in their owning repositories.
