# FAQ

This reference covers common questions about the current source interface.
Check your deployment revision and the installed scenario before applying an answer.

## Provisioning

**How long does provisioning take?**

There is no fixed duration.
Images, capacity, bootstrap work, and backend conditions affect the time.
A displayed **Provisioning** status does not prove that an operation has failed.

**Why is my range stuck in Provisioning?**

Use [range troubleshooting](../how-to/troubleshooting.md#range-issues).
Keep the range identity and displayed error for the operator.
Do not cancel and relaunch solely because a fixed number of minutes has passed.

**Can I cancel a provisioning range?**

Use **Cancel launch**, then wait for verified cleanup.
Cancellation dispatch and resource removal are separate results.

## Ranges

**Can I have multiple ranges at once?**

The Mission Control workflow allows one active range per acting principal.
Workspace quotas and launch permissions also apply.
CTF ranges follow their event lifecycle.

**How do I destroy a range?**

Follow [Destroy a range](../features/ranges.md#destroy-a-range).
Destruction removes guest data and is irreversible.
An accepted request is not proof of completed cleanup.

## Agents

**What agent formats are supported?**

See the [installer format table](../features/agents.md#supported-formats).
The server checks the extension and file header.

**How much storage do I have?**

Defaults are 2 GiB per file and a 5 GiB budget for the authorized content scope.
The [agent guide](../features/agents.md#storage-limits) explains upload reservations.

**Where do I download agents?**

Use your approved XDR/XSIAM, XDR Collector, or Cloud Identity Engine distribution source.
A scenario with an explicit no-agent contract does not require an upload.

## Alerts

**Where do alerts appear?**

Configured endpoint and network integrations send telemetry to the selected external console.
BigRAE does not guarantee that an exercise produces an alert or a fixed delivery delay.

**Why are alerts absent?**

Check the installed agent's connection, the approved detection test, and the console filters.
Use [agent troubleshooting](../how-to/troubleshooting.md#no-alerts-in-console-after-attack).

## NGFW

**Do I need an NGFW for a basic exercise?**

Only if the scenario requires it.
The GCE range-cell path does not support the retained NGFW attachment contract.
See [scenario capabilities](../scenarios/index.md#gcp-vm-range-cell-support).

**Why does NGFW setup require credentials?**

SCM registration and software licensing use separate [deployment credentials](../features/credentials.md).
Those credentials are not platform API tokens.

## Releases

The latest release checked on 2026-11-09 is `v4.1.1`.
It predates the GCP deployer container.
Use the [installation release check](../getting-started/install-gcp.md#3-select-and-verify-a-release) before any deployment command.
Backend code or a contributor deployment does not establish published-release support.
