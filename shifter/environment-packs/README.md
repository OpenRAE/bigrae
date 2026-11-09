# Shifter-owned environment packs

Reference for the public example collection and how to ship a pack.

This directory is the one canonical source location for the environment packs
that Shifter owns. Each subdirectory is an independent, complete RAES
environment pack. The directory name is the pack name. Do not keep copies of
these packs anywhere else in the repository.

| Pack | Purpose | Shipped and registered by default |
|---|---|---|
| `smoke-linux` | Post-deploy smoke range for the GCP range backend | Yes |
| `smoke-linux-aws` | Portable-addressing smoke range for the AWS EC2 range backend | Yes |
| `preparation-http-smoke` | In-tenant artifact preparation specimen | No |
| `shifter-raes-validation` | Live RAES backend validation pack | No |

## Shipment and registration

A pack in this directory is a source only. It is not shipped in an image and
it is not registered automatically. Two explicit declarations select a shipped
pack:

1. `shifter/shifter_platform/Dockerfile` copies the pack into the portal image
   at `/app/cms/scenarios/inbox_packs/<pack>`.
2. `shifter/shifter_platform/cms/scenarios/inbox_packs/manifest.yaml` declares
   the pack with that runtime path as its `package_ref`. The deploy bootstrap
   (`bootstrap_inbox_catalog`) registers each manifest entry through the
   standard `register_pack` service and promotes its release conformance.

The `package_ref` names the runtime destination in the image, not the source
path. Stored CMS registrations therefore do not change when the source moves.
See the [in-box bootstrap README](../shifter_platform/cms/scenarios/inbox_packs/README.md)
for the steps to ship a new pack.

## Development packs

Packs that are not in the manifest stay out of the portal image. Tests read
them from this directory. To register one manually in a checkout, use the
default `RAES_PACKAGE_ROOT` (the repository root) and the
`shifter/environment-packs/<pack>` package reference. See
[content ingestion](../../docs/ops/content-ingestion.md).

## Routing

- A change to a shipped pack triggers the portal image build, the built-image
  stack smoke, and the portal deploy.
- A change to a development pack runs Quality only.
- Quality runs the platform pack tests for every pack. It also runs the
  provisioner tests for `shifter-raes-validation`.

The `deploy-workflow-plan-scope` ADR guard keeps this routing in agreement with
the Dockerfile copies.

## Build output

Do not commit generated output under `<pack>/build/`. The
`no-tracked-generated-artifacts` ADR guard rejects it.

## Example contracts and preserved records

`smoke-linux` and `smoke-linux-aws` test provision, SSH connectivity, and teardown.
Each declares two Linux guests on one network.
The AWS example leaves CIDR, gateway, and guest addresses to the backend.
Neither example supplies scenario answers or authored participant credentials.

`preparation-http-smoke` declares an Ubuntu 22.04 HTTP service on port 8080.
Its preparation declaration grants no execution authority.
Install and approve the adapter separately; the selected backend must provide isolated networking.

`shifter-raes-validation` exercises one VM, one network, content placement, a public-key account, and digest-bound configuration.
The validation command requires observed evidence for the composition resources.
Topology alone is insufficient.

Each pack's `docs/concepts.md` and provenance ledger belong to its associated-artifact inventory.
Those bytes are preserved with their published identity.
Do not edit them for style without a normal pack revision and regenerated owner metadata.
Use the released environment-pack tooling; do not construct a parallel digest generator.
Registration, conformance, backend admission, runtime readback, and live qualification are separate results.
See [scenario contracts](../../docs/technical/handbook/scenario-contract-transition.md) for the supported versions.
