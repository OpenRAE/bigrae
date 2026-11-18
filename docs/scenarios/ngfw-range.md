# Basic Range with NGFW

Use this guide only for an installed pack and backend that support the required firewall attachment.
The GCE range-cell path rejects the retained NGFW attachment and segmented-routing capability.
Do not use this page as a GCP launch procedure.

## Architecture

A compatible pack declares attacker and target networks with firewall attachment between them.
The installed contract determines routing and telemetry; the page title does not establish either.

## Instances

Check the pack's guest images, endpoint installer needs, and firewall reference.

## Network

Have the operator verify the declared segmentation and supported firewall attachment.
Do not assume every guest flow passes through a firewall.

## Prerequisites

Use the operator-owned [NGFW setup guide](../how-to/ngfw-demo.md) for provisioning and integration.
Confirm backend compatibility and a ready firewall before a launch.
SCM association, licensing, and log forwarding need their own successful results.

## Access

Use [Terminal](../features/terminal.md) for guest access.
Use the [NGFW management flow](../features/ngfw.md#accessing-ngfw-management) for the firewall.

## Use cases

Use only the authorized firewall policy and endpoint/network telemetry tests.
The operator defines permitted destinations and expected evidence.

## Launch steps

1. Confirm the compatible backend, installed pack, and ready firewall with the operator.
2. Open **Ranges > Launch a range**.
3. Select the approved workspace and scenario.
4. Select the installer required by that scenario.
5. Select **Launch range**.
6. Wait for **Ready** and check the pack's routing verification.
7. [Destroy the range](../features/ranges.md#destroy-a-range) after the exercise.

Range cleanup does not necessarily destroy a separately managed persistent firewall.
Ask its operator to remove unused firewall resources through the setup procedure.

## What you see in XDR/XSIAM

Endpoint and network alerts depend on successful agent enrollment, log forwarding, filters, and the approved test.
BigRAE does not guarantee an alert, correlation, or delivery time from a successful launch.
