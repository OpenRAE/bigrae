# Troubleshooting guide

Use this guide for user, range, installer, and connection failures.
Keep the displayed error and affected range identity before changing anything.
Use [operations runbooks](../runbooks/index.md) for deployment or provider recovery.
Do not send raw credentials, pack content, or unredacted logs to a public issue.

## Range issues

### Range stuck in Provisioning {#range-stuck-in-provisioning}

Provisioning duration depends on capacity, images, and guest setup.
Elapsed time alone does not prove failure.

1. Check the displayed status and operation error.
2. Refresh status if the live connection is offline.
3. Ask the operator to inspect the accepted operation if progress remains unknown.
4. Use **Cancel launch** only when cancellation is the intended action.
5. Confirm terminal cleanup before another launch.

Do not retry by deleting database rows, state, or locks.

### Range shows Failed

1. Record the range identity and safe error code.
2. Check that the selected scenario is enabled and realizable on this backend.
3. Confirm required images, adapter bindings, installers, and workspace authority with the operator.
4. Resolve the reported cause.
5. [Destroy the failed range](../features/ranges.md#destroy-a-range) and confirm cleanup before a fresh launch.

Changing to an unrelated scenario does not resolve the original operation.

<a id="cant-launch-range---already-have-active-range"></a>

### Cannot launch range: already have active range {#cant-launch-range-already-have-active-range}

Open **Ranges** and inspect the existing range.
Finish or destroy it through its lifecycle controls.
Wait for cleanup confirmation before launching another Mission Control range.
For a lost API response, use the [original retry key](../features/retry-safe-range-operations.md).

## Terminal issues

### Terminal cannot connect {#terminal-wont-connect}

1. Confirm that the range is **Ready** and the selected device is correct.
2. Read the connection error or close reason.
3. Check that the scenario declares the selected protocol.
4. Ask the operator to inspect guest readiness when the service is unavailable.
5. Reconnect only after correcting the cause.

Current permission and credential checks also apply while a session is connected.
A revoked credential or unavailable authority service can close it.

### Terminal disconnects frequently

Check your network and the displayed connection reason.
Use **Reconnect** when the error permits it.
Switching device tabs replaces the visible connection.
Use a guest session that can survive reconnection for long-running authorized work.

### RDP button does nothing

Permit popups from the portal and select **RDP** again.
Read the queue or connection error if a session is refused.
An RDP button does not prove that the image has a working desktop service.
Ask the operator to verify the guest's access contract.

## Agent issues

### Upload fails

1. Check the deployment's displayed per-file limit.
2. Confirm available storage in the destination content scope.
3. Check the supported extension and matching file header.
4. Obtain a fresh installer from the approved source if the file is damaged.
5. Resolve the error before a new upload submission.

Defaults are 2 GiB per file and a 5 GiB scoped storage budget.
Pending uploads reserve budget too.
See [Agents](../features/agents.md).

### Agent shows wrong OS

The validator maps supported extension/header formats to OS categories.
It does not inspect every installer payload or prove guest compatibility.
A `.zip` upload maps to Windows; `.tar.gz` and `.tgz` map to generic Linux.
Debian and RPM packages have their own mappings.
Do not rename a file to force a different platform.
Ask an authorized content administrator to retire an incorrect upload.

### No alerts in console after attack

1. Confirm endpoint enrollment and connection in the approved console.
2. Confirm that the installed scenario performs the expected installer work.
3. Use the approved detection test for the exercise.
4. Check the console's time range and alert filters.
5. Ask the console owner to inspect telemetry delivery.

The Linux smoke tutorial does not install an endpoint agent or promise an alert.
Do not introduce malware or external targets to compensate for missing telemetry.

## NGFW Issues

Use the [NGFW setup and recovery guide](ngfw-demo.md#troubleshooting) for provider investigation and cleanup.
The checks below do not authorize a second provisioning operation.

### NGFW Stuck Provisioning

Record the request id, NGFW id, status, and last bounded error.
Check the cloud operation, capacity, licensing, and credential metadata before retrying.
The earlier 15–30 minute estimate and 45-minute escalation point are not proof of failure.
Do not deprovision an active operation solely because an estimate elapsed.

### Cannot Associate Device in SCM { #cant-associate-device-in-scm }

Confirm the serial number and folder authority with the SCM owner.
Check PIN metadata without exposing its value.
A successful external association does not prove application readiness.

### NGFW-Enabled Range Will not Launch { #ngfw-enabled-range-wont-launch }

Confirm the NGFW is ready and the selected scenario is installed and admitted.
The GCE range-cell path does not support the retained NGFW attachment contract.
A ready standalone firewall cannot supply that capability.
See [NGFW scenario limits](../scenarios/ngfw-range.md).
Check the owning range operation before another launch.
Use [RB001](../runbooks/rb001-range-provisioning-failed.md) for a failed provisioning operation.

### No Network Alerts in XDR/XSIAM

Check firewall log generation, forwarding, SCM ingestion, and XDR/XSIAM ingestion separately.
Use an approved synthetic sample with the security owner.
HTTP traffic and ICMP exercise different paths.
An endpoint alert alone does not prove network-log delivery.

## Account issues

### Cannot access certain features {#cant-access-certain-features}

Confirm the deployment URL, active login, selected scope, and requested permission.
Ask an authorized administrator to inspect the relevant policy and credential ceiling.
Membership, ownership, and staff status do not automatically grant every action.
Do not change cloud IAM to bypass an application denial.

## Getting more help

Record the task, deployment revision, safe error code, request identifier, and range identity when available.
Remove secrets and private scenario material before sharing evidence.
Follow [support guidance](../reference/support.md) for the approved reporting channel.
