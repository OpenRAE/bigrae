# Launch your first range

In this tutorial, launch a Linux range, inspect its two guests, and destroy it.
Use only the deployment and guests that your operator authorizes for this exercise.
The commands below read local guest information and print a test message.

## Before you start

Use an installed, operator-qualified GCP tenant with the public `smoke-linux` scenario enabled.
Ask the operator to confirm its image mappings and launch prerequisites.
Sign in with permission to launch and access a range in the selected workspace.
Your account must have no active Mission Control range.

For installation, follow [Install on Google Cloud](install-gcp.md).
The current tutorial follows the source interface checked on 2026-11-09.
The latest published release, `v4.1.1`, predates that installation route.
An eligible published-release exercise and live-cloud execution remain unverified.

## 1. Check agent requirements {#1-upload-an-agent}

The current `smoke-linux` contract does not need an endpoint agent installer.
Skip the upload for this exercise.
If the form requires an agent, stop and ask the operator to check the selected scenario and deployment revision.
For another scenario that requires one, follow [Upload an agent](../features/agents.md#upload-an-agent).

## 2. Launch the range

1. Open **Ranges** in the sidebar.
2. Confirm that the page shows **No active range**.
3. Select **Launch a range**.
4. Select the workspace that your operator approved.
5. In **Scenario**, select `smoke-linux`.
6. Select **Launch range**.

The range page shows the accepted launch.
Its status can pass through **Pending** and **Provisioning** before **Ready**.
Provisioning time depends on the deployment; this tutorial promises no fixed duration.
Do not launch another copy while the first operation is pending.

If launch fails, read the displayed error.
Use [range troubleshooting](../how-to/troubleshooting.md#range-issues) before you retry.

## 3. Connect to the range

1. Wait for **Ready**.
2. Open **Terminal**.
3. Select the `attacker` device.
4. Wait for the SSH prompt.
5. Run these commands:

```shell
whoami
printf 'first-range-check\n'
```

The user name is `kali`.
The next command prints `first-range-check`.
This confirms that you can send a command to the attacker guest.

Select the `victim` device and run the same commands.
The user name is `ubuntu`, followed by the same test message.
The smoke scenario declares SSH access to both devices.
It does not require an RDP session or an endpoint detection test.

If a connection fails, use [terminal troubleshooting](../how-to/troubleshooting.md#terminal-issues).
Keep the range identity for the operator.

## 4. Destroy the range

Destruction removes this exercise's range resources and guest data.
It does not remove the BigRAE installation or its uploaded assets.

1. Return to **Ranges**.
2. Confirm that the active range is the one you created.
3. Select **Destroy**.
4. Confirm with **Destroy**.
5. Wait for cleanup to finish.
6. Check the range history for the terminal **Destroyed** result.
7. Confirm that **Ranges** shows **No active range**.

A **Destroying** status means cleanup is still running.
An accepted request alone does not prove that resources are gone.
If cleanup fails or stays unknown, ask the operator to use the [operations runbooks](../runbooks/index.md).
Do not repeat the exercise until cleanup is confirmed.

## Next steps

- [Key concepts](concepts.md) explains the objects used in this exercise.
- [Range operations](../features/ranges.md) covers later launches, leases, and cleanup.
- [Retry-safe operation reference](../technical/shifter_platform/retry-safe-range-operations.md) defines API retries and cleanup outcomes.
- [Scenario catalog](../scenarios/index.md) helps you inspect other installed scenarios.
- [CTF organizer guide](../features/ctf-organizer-guide.md) covers event tasks.
