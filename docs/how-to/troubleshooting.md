# Troubleshooting Guide

Common issues and how to resolve them.

## Range Issues

### Range Stuck in "Provisioning"

**Symptoms**: Status shows "Provisioning" for more than 10 minutes.

**Solutions**:

1. Wait a bit longer - some scenarios take 10-15 minutes
2. Cancel the range and relaunch
3. If repeated failures, check your agent file is valid

### Range Shows "Failed"

**Symptoms**: Status shows "Failed" with an error message.

**Solutions**:

1. Read the error message - it usually indicates the cause
2. Check your agent file:

   - Is it the right format for the OS you selected?
   - Is the file corrupted? Try re-downloading from your console
3. Try a different scenario (Basic Range is most reliable)
4. Destroy and relaunch

<a id="cant-launch-range-already-have-active-range"></a>

### Cannot Launch Range - "Already Have Active Range" { #cant-launch-range---already-have-active-range }

**Symptoms**: Launch button disabled or error about existing range.

**Solution**: Destroy your current range first. Go to Ranges, click Destroy on the active range.

## Terminal Issues

### Terminal Will not Connect { #terminal-wont-connect }

**Symptoms**: Terminal shows "Connecting..." indefinitely or "Not connected."

**Solutions**:

1. Refresh the page
2. Wait a minute - instance may still be starting
3. Check if range is in "Ready" status
4. Try a different browser

### Terminal Disconnects Frequently

**Symptoms**: Connection drops, have to reconnect.

**Solutions**:

1. Check your network connection
2. Avoid letting the browser tab go idle for long periods
3. Refresh and reconnect

### RDP Button Does Nothing

**Symptoms**: Clicking RDP does not open a new window.

**Solutions**:

1. Check browser popup blocker - allow popups from BigRAE
2. Try right-click > "Open in new tab"
3. Wait for instance to fully boot (RDP service may not be ready)

## Agent Issues

### Upload Fails

**Symptoms**: Upload errors or stuck at 0%.

**Solutions**:

1. Check file size - max 2 GB per file
2. Check total storage - max 5 GB across all agents
3. Verify file format is supported
4. Try a different browser
5. Check network connection

### Agent Shows Wrong OS

**Symptoms**: Agent listed as wrong platform.

**Cause**: OS is detected from file format, not contents.

**Solution**: If detection is wrong, delete and re-upload with correct format. Ensure you are using:

- `.msi` or `.zip` for Windows
- `.tar.gz` for Linux shell installer
- `.deb` for Debian/Ubuntu
- `.rpm` for RHEL/CentOS

### No Alerts in Console After Attack

**Symptoms**: Running attacks but no alerts appear.

**Solutions**:

1. Verify agent is installed and connected:

   - Check your XDR/XSIAM console for agent status
   - Agent should show as "Connected" or similar
2. Run a more obvious attack:

   - Execute known malware samples
   - Run detection test tools
   - Trigger behavioral detections
3. Check console filters:

   - Ensure you are looking at the right time range
   - Check severity filters are not hiding alerts
4. Wait a few minutes - some alerts take time to process

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
Check the owning range operation before another launch.
Use [RB001](../runbooks/rb001-range-provisioning-failed.md) for a failed provisioning operation.

### No Network Alerts in XDR/XSIAM

Check firewall log generation, forwarding, SCM ingestion, and XDR/XSIAM ingestion separately.
Use an approved synthetic sample with the security owner.
HTTP traffic and ICMP exercise different paths.
An endpoint alert alone does not prove network-log delivery.

## Account Issues

### Cannot Access Certain Features { #cant-access-certain-features }

**Symptoms**: Buttons disabled, features unavailable.

**Solutions**:

1. Ensure you are logged in
2. Check if feature requires setup first (for example NGFW scenarios require NGFW)
3. Contact support if you believe this is an error

## Getting More Help

If none of these solutions work:

1. Note the exact error message
2. Note what you were trying to do
3. Contact support (see [Support](../reference/support.md))
