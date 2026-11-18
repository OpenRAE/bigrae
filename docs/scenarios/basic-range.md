# Basic Range

Use this guide for an operator-installed attacker-and-victim scenario.
The name does not identify a guaranteed entry in every deployment.
For the public GCP exercise, use [Launch your first range](../getting-started/quickstart.md).

## Architecture

The exercise places an attacker and a victim in the pack's declared network.
An installed endpoint agent can send telemetry to its approved console.
The pack and backend determine the actual topology.

## Instances

Check the catalog detail for guest images, roles, and agent requirements.
Do not infer the victim OS solely from the display name.
The selected installer and scenario contract must be compatible.

## Network

Ask the operator to confirm the scenario's isolation and outbound access policy.
Do not assume that all guests or external destinations are reachable.

## Access

Use the channels declared by the pack and supported by the realized image.
See [Terminal](../features/terminal.md).

## Use cases

Use the range for approved endpoint tests and attacker-victim exercises.
Keep the test within the authorized guests and network boundaries.

## Launch steps

1. Ask the operator which installed scenario implements this exercise.
2. Check its catalog detail and realizability.
3. Open **Ranges > Launch a range**.
4. Select the approved workspace and scenario.
5. Select an agent only when the scenario requires one.
6. Select **Launch range**.
7. Wait for **Ready** before connecting.
8. Follow [range cleanup](../features/ranges.md#destroy-a-range) when finished.

## What is installed? {#whats-installed}

### Kali attacker

The pack's selected image defines the installed tools.
A generic Kali label does not guarantee particular tool versions.

### Victim workstation

The pack declares the guest configuration and any installer work.
Check the endpoint console to confirm agent enrollment before a detection test.
