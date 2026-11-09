# NGFW

Use an operator-prepared Next-Generation Firewall only on a compatible backend.
The current GCE range-cell path does not support the retained NGFW attachment contract.
Do not infer supported GCP use from the presence of a setup screen.

## What is NGFW

An NGFW can supply firewall policy and network telemetry for a compatible range.
The scenario and backend must support its attachment and routing requirements.
The firewall is managed separately from an ordinary guest range.

## Prerequisites

Have the operator confirm backend support, licensing, SCM registration, and log-forwarding prerequisites.
Integration secrets use [Credentials](credentials.md), not platform personal tokens.
You need current permission to manage or access the firewall.

## Setup wizard

Use the operator-owned [NGFW setup guide](../how-to/ngfw-demo.md) for provisioning and integration steps.
This page covers user launch and access after successful setup.

### Step 1: Name and profile

Use the approved deployment profile identifier from the operator's procedure.

### Step 2: Registration

Use the approved SCM credential identifier.

### Step 3: Confirmation

Confirm the intended firewall and destination before a cost-bearing operation.

### Step 4: Provisioning

Monitor the actual operation result.
This guide provides no fixed provisioning-time guarantee.

## After provisioning

Ask the operator to verify licensing, SCM association, routing, and log forwarding.
Then select the installed compatible scenario through [range launch](ranges.md#launch-a-range).
The current public bootstrap catalog does not guarantee a legacy NGFW scenario entry.

## Accessing NGFW management

### CLI access

1. Open **Assets > NGFWs**.
2. Select the ready firewall.
3. Under **CLI access**, select **Open CLI**.
4. Permit the new session tab if the browser blocks it.
5. Read any session error before retrying.

The portal brokers the authorized SSH session.
It does not expose a generic tunnel to your local computer.

### GUI access

The current detail page provides CLI access, not a general GUI launch control.
Use only an operator-approved management network and credential procedure for the PAN-OS web interface.
Do not infer a reachable management address from an open browser SSH session.

## Managing NGFWs

The list shows firewall state and metadata.
Use **Deprovision** only when authorized to remove the persistent firewall.
Confirm that no exercise still depends on it.
Follow the operator procedure to verify resource and license cleanup.

## NGFW status

Use the reported state and operation error for the selected firewall.
A ready firewall alone does not prove that a range has the required attachment or that telemetry reaches a console.

## Tips

Range destruction and persistent-firewall deprovisioning are separate operations.
Coordinate both with the operator to avoid leaving unused resources.
See [NGFW scenario limits](../scenarios/ngfw-range.md).
