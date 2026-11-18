# Scenarios

Use this guide to inspect the installed catalog and choose a scenario.
The current catalog contains registered RAES packs.
It does not provide the retired form or YAML scenario editor.

## Available scenarios

1. Open **Author > Scenarios** with content-read permission for the selected catalog.
2. Select the **Catalog** scope.
3. Search by scenario name or identifier.
4. Check **Availability** and **Launchable**.
5. Open the scenario name for its details.

The details show package version, conformance, digest, and realizability.
Use the realizability result for the configured backend.
An enabled entry alone does not prove that images, adapters, capacity, and permissions permit a launch.
Availability changes require content-management authority; the server checks every request.

## GCP VM range-cell support

The public bootstrap catalog includes `smoke-linux` and the portable-addressing `smoke-linux-aws` variant.
Use the GCP variant for the [first-range tutorial](../getting-started/quickstart.md).
The AWS variant's presence does not establish a supported AWS release installation.

Other packs depend on the operator's installed content and capability configuration.
The GCE path rejects unsupported NGFW attachment and segmented routing before provider mutation.
Domain-controller compositions require matching, pre-promoted image metadata.
Do not infer live support from a scenario name or a retained design.
See [scenario verification](../technical/shifter_platform/scenario-verification.md) for exact checks.

## Install a content pack

You need permission to manage adapters and pack content for the chosen organization.
Obtain an approved `.tar`, `.tar.gz`, or `.tgz` archive from its owner.

1. Open **Administer > Adapters**.
2. Select the organization.
3. Select **Install packs and assign adapters**.
4. Under **Install a content pack**, select **Install a new pack**.
5. Enter the author's **Pack name**.
6. Select the **Pack archive**.
7. Select **Review pack installation**.
8. Check the organization and archive, then select **Install pack**.
9. Confirm the installed version in the result.

For an update, select the existing installation instead of entering a new name.
Existing ranges keep their original version.
Review the adapter binding before later launches.

Pack validation does not install executable adapters or start a range.
Install and assign any required adapter separately through the administrator controls.
A compatibility probe alone does not qualify a live range.
See [artifact preparation](../ops/artifact-preparation.md) for operator setup and the [public adapter SDK](https://github.com/OpenRAE/bigrae/tree/dev/shifter/shifter_adapter_sdk) for contracts.

## Quick comparison

The retained scenario pages describe exercise patterns, not a guaranteed installed inventory:

- [Basic Range](basic-range.md): an attacker and a victim.
- [AD Attack Lab](ad-attack-lab.md): a domain-controller exercise.
- [Basic Range with NGFW](ngfw-range.md): a compatible firewall attachment exercise.

Use the installed pack's declared guests, agent needs, and access channels for an actual launch.

## Provisioning time

Provisioning time varies with images, bootstrap work, capacity, and backend conditions.
This guide gives no fixed timing guarantee.
Use [range monitoring](../features/ranges.md#monitor-provisioning) and the displayed operation result.
