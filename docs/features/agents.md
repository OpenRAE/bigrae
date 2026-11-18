# Agents

Upload an approved endpoint installer for a scenario that requires one.
The scenario determines which guests receive it.
Uploading an installer alone does not install it on a running guest.

## What is an agent? {#whats-an-agent}

An agent is an XDR/XSIAM, XDR Collector, or Cloud Identity Engine installer.
It is separate from a runtime adapter and a platform API credential.
Confirm the required installer type with the scenario owner.

## Supported formats

The server checks both the extension and the file header.
A matching header does not prove that an installer is safe or compatible with every guest.

| Installer | Extension | Detected platform |
| --- | --- | --- |
| Windows Installer | `.msi` | Windows |
| ZIP archive | `.zip` | Windows |
| Gzip tarball | `.tar.gz`, `.tgz` | Generic Linux |
| Debian package | `.deb` | Debian Linux |
| RPM package | `.rpm` | RHEL Linux |

## Storage limits

The default per-file ceiling is 2048 MiB, or 2 GiB.
The default storage budget is 5120 MiB, or 5 GiB, for the authorized content scope.
Pending uploads also reserve space in that budget.
Use the upload limit shown by your deployment; do not rename a file to bypass validation.

## Upload an agent

You need content-management permission for the destination scope.
Obtain the installer from its approved source before starting.

1. Open **Assets > Agents**.
2. In **Upload agent**, enter an **Agent name**, such as `Example Linux installer`.
3. Select the **Agent type**.
4. Select the **Installer file**.
5. Select **Upload agent**.
6. Wait for the new row in the agent list.
7. Check its type, detected OS, filename, and size.

A failed upload shows an error.
Correct the cause before a fresh submission; the form does not retry automatically.
Select **Cancel** to stop an upload in progress.

## Manage agents

The current SPA lists uploaded installers and their metadata.
It does not provide a delete action in this table.
Ask an authorized content administrator to retire an installer through the supported service interface.
See [troubleshooting](../how-to/troubleshooting.md#agent-issues) for upload failures.

## Tips

Use names that identify the operating system and installer version.
Use only installers approved for the exercise and the destination scope.
