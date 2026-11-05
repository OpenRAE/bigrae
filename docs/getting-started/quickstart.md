# Launch your first range

This page launches the `smoke-linux` scenario on a new deployment and then
destroys it. To install BigRAE first, see
[Install BigRAE on GCP](../technical/handbook/gcp-first-run.md).

## Before you start

- Sign in to the portal with an account that can launch ranges. The first
  administrator can.
- Have an agent installer file. The launch form requires an agent, but the
  `smoke-linux` scenario does not install it.

## 1. Upload an agent

1. In the sidebar, select **Assets > Agents**.
2. In **Upload agent**, enter an **Agent name**.
3. Select the **Agent type**.
4. Select the **Installer file**.
5. Select **Upload agent**.

## 2. Launch the range

1. In the sidebar, select **Ranges**.
2. Select **Launch a range**.
3. In **Scenario**, select the `smoke-linux` scenario.
4. In **Agent**, select the agent that you uploaded.
5. Select **Launch range**.

The range status changes from **Pending** to **Provisioning** to **Ready**.

## 3. Connect to the range

1. In the sidebar, select **Terminal**.
2. Select the tab of a device. The `smoke-linux` range has two devices:
   - `attacker`: Kali;
   - `victim`: Ubuntu.

The terminal opens an SSH session on the device.

## 4. Destroy the range

1. In the sidebar, select **Ranges**.
2. Select **Destroy**.
3. Confirm with **Destroy**.

## Next steps

- [Key concepts](concepts.md): the terms that the portal uses.
- [Artifact preparation](../ops/artifact-preparation.md): register your own
  scenario pack.
- [CTF organizer guide](../features/ctf-organizer-guide.md): run a CTF event.
