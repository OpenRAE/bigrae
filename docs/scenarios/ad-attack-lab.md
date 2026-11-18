# AD Attack Lab

Use this guide for an operator-installed Active Directory exercise.
The current public bootstrap catalog does not guarantee an AD lab entry.
Ask the operator to identify and qualify the installed pack before launch.

## Architecture

The pack defines the domain controller, member guests, attacker, and their network relationships.
The catalog and realized result define what is available in your deployment.

## Instances

Check each image, role, agent requirement, and access channel in the pack's reference.
Do not assume a tool or desktop is present from its OS name.

## Network

Confirm the permitted guest-to-guest paths and outbound access before the exercise.
Use only the network and accounts authorized by the operator.

## Domain configuration

The installed pack owns its DNS domain, NetBIOS name, and domain membership intent.
For GCE, a domain controller requires an exact matching pre-promoted image profile.
A generic Windows image is insufficient.
See [scenario verification](../technical/shifter_platform/scenario-verification.md).

## Access

Use [Terminal](../features/terminal.md) for the pack's supported SSH or RDP channels.
Store supplied credentials in the approved credential store.

## Use cases

Run only the authorized domain enumeration, credential, lateral movement, or Kerberos exercise.
The pack owner supplies the exercise objectives and accepted evidence.

## Launch steps

1. Confirm that the installed pack and domain images are qualified for the backend.
2. Open **Ranges > Launch a range**.
3. Select the approved workspace and scenario.
4. Select the required compatible installer.
5. Select **Launch range**.
6. Wait for **Ready**.
7. Check the declared domain membership before starting the exercise.
8. [Destroy the range](../features/ranges.md#destroy-a-range) when finished.

## What is installed? {#whats-installed}

### Kali attacker

The image and pack define the tools and versions.
No specific AD tool set is guaranteed by this page.

### Domain controller

The image must satisfy the authored domain contract.
Ask the operator to resolve a domain capability error before retrying.

### Workstation

Confirm domain membership and endpoint enrollment through the pack's verification steps.
A **Ready** range is not proof that a particular detection succeeded.
