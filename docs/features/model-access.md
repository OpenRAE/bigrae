# Model sources for scenarios and CTFs

Use this guide to administer a model source in an authorized organization.
The model broker and its shared-budget controls remain unsupported under [ADR-068](../adr/068-model-access-broker-parked.md).
Keyless-direct is the supported guest model path.
A retained broker screen or enabled setting does not activate a supported broker service.

## Connect a source

1. Open **Administer > Model sources**.
2. Select the organization you are authorized to manage.
3. Select **Add model source**.
4. Select the provider and enter its required configuration.
5. Enter the model, identity, region where required, context limit, and price information.
6. Save the source and inspect the result.

The provider determines whether configuration uses workload identity or an approved credential.
Secrets are write-only and clear after each attempted submission.
An edit without a new credential retains the stored credential.
Use current organization policy to authorize source administration and use separately.

**Configured** means the source was saved.
It does not prove provider connectivity, quota, deployment qualification, or permission to spend.
The source's token ceiling is an application limit, not purchased provider quota.
An expired price blocks new admission.
A zero price records zero monetary reservation for that component; other limits remain independent.

## Choose sources at launch

Select the workspace and scenario before choosing an authorized source for each model alias.
Keep deployment defaults when they match the approved exercise.
A selection does not bypass allowed regions, provider capacity, scenario compatibility, or current authority.
It does not turn on the parked broker.
See [operator model guidance](../ops/model-access.md) before relying on retained broker-dependent controls.

## Configure a CTF

Use the event's model-source picker only with event configuration and source-use authority.
Participants do not receive the organizer's provider credentials.
A saved selection or planning assessment does not prove runtime model access.
Have the operator qualify the supported guest path before the event.

## Share model access across ranges

The retained sharing API is unavailable while the broker is parked.
It refuses before membership reads or publication.
Do not use retained sharing forms to establish a shared budget or provider grant.

## What participants see

A range page can show logical model aliases and an availability state.
It does not expose provider credentials or another participant's usage.
Check the qualified direct-access path with the operator when availability is unknown.

## Change an existing range

Use **Range model sources** only for independently supported source administration.
A revision conflict requires a reload before another change.
Source or grant revocation does not refund spend or prove that a billed provider request stopped.
Keep outstanding usage and unresolved charges under their original accounting.

For retained provider, allocation, sharing, and renewal contracts, use the [architecture explanation](../technical/architecture.md).
The [operator guide](../ops/model-access.md) distinguishes parked implementation from qualified deployment behavior.
