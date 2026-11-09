# Key concepts

This explanation describes the objects used in the first-range tutorial.

## Release

A release identifies one published source revision and its available artifacts.
The GCP container installation route requires control-plane images, a deployer image, and verified provenance.
The latest release checked on 2026-11-09, `v4.1.1`, predates that deployer.
See [release selection](install-gcp.md#3-select-and-verify-a-release).

## Deployment

A deployment is one installation of BigRAE with its own configuration and portal address.
Cloud IAM authorizes cloud operations.
Application policies separately authorize actions inside BigRAE.

## Scenario

A scenario defines the intended devices, networks, and access for a range.
An administrator installs scenario content as an environment pack.
The catalog reports availability and realizability for the configured backend.
Those results do not prove live qualification.

The public `smoke-linux` scenario declares a Kali attacker and an Ubuntu victim.
Other scenarios depend on the deployment's installed catalog and image mappings.
See [scenario selection](../scenarios/index.md).

## Range

A range is one realized scenario with its own identity, owner, scope, and lifecycle.
A workspace groups resources; membership alone does not grant access to another principal's range.
The platform checks current permissions and credential limits for each operation.
Cleanup is complete only when the platform verifies the terminal result.

## Agent

An endpoint agent is an uploaded installer, such as an XDR/XSIAM package.
A scenario can require that installer for selected guests.
A no-agent scenario can launch without one.
An executable runtime adapter is a separate administrator-managed component.

## Terminal

The terminal provides browser access to authorized range devices.
SSH, RDP, and file-transfer capabilities depend on the guest and its access contract.
See [terminal tasks](../features/terminal.md) and the [architecture explanation](../technical/architecture.md).
