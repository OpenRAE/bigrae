# Key concepts

## Release

One published version of BigRAE: the control-plane images and the deployer
image, with signed build provenance. A deployment runs exactly one release.
See [Select and verify a release](install-gcp.md#3-select-and-verify-a-release).

## Deployment

One installation of BigRAE in one GCP project, with one portal hostname.

## Scenario

A template that defines the devices, networks, and access of a range. An
administrator registers each scenario as an environment pack. A new deployment
has one scenario, `smoke-linux`: a Kali attacker and an Ubuntu victim.

## Range

A running copy of a scenario. Each range has its own isolated network. A range
does not affect other ranges.

## Agent

An installer file that you upload. A scenario can install it on its devices
when the range launches.

## Terminal

Browser access to the devices of a range.
