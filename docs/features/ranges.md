# Ranges

Launch and manage a range in an authorized workspace.
For a bounded exercise, use the [first-range tutorial](../getting-started/quickstart.md).
The installed scenario and backend determine the available capabilities.

## Range lifecycle

Launch acceptance starts an asynchronous operation.
The platform reports provisioning, operation errors, and cleanup separately.
A teardown request must reach a verified terminal result before you treat resources as removed.

## Status reference

| Status | Meaning |
| --- | --- |
| Pending | The range is queued. |
| Provisioning | Resource creation and guest setup are running. |
| Ready | The range is available for its supported access paths. |
| Paused | A supported pause operation has completed. |
| Destroying | Cleanup is in progress. |
| Failed | The operation failed; inspect its result. |
| Destroyed | The range reached its terminal cleanup state. |

Use the displayed operation result when cleanup evidence is pending or unknown.
A timeout or missing worker response is not successful destruction.

## Launch a range

You need current launch authority and a credential that permits the selected scope.
You must also satisfy scenario, installer, quota, and backend admission checks.
Membership or a visible launch button alone does not establish that authority.

1. Open **Ranges**.
2. Select **Launch a range**.
3. Select the approved **Workspace**.
4. Select the installed **Scenario**.
5. Select an **Agent** only when the scenario contract requires one.
6. Select **Launch range**.
7. Read the accepted operation or error.

The current workflow allows one active Mission Control range per acting principal.
Do not submit another launch to recover a lost API response; use [retry-safe operations](retry-safe-range-operations.md).

## Monitor provisioning

The range page updates status while connected.
If live updates disconnect, use the displayed connection information and refresh the status.
Provisioning has no fixed duration.
Read a failure result before cancellation or another launch.
See [range troubleshooting](../how-to/troubleshooting.md#range-issues).

## Access a range

When **Ready**, open **Terminal** and select an authorized device.
Use the scenario's supported SSH or RDP path.
A displayed device is not a guarantee that every protocol is configured.

When the range advertises VPN access, select **Download VPN profile**.
Keep the `.ovpn` file private and remove your local copy when no longer needed.
See [terminal tasks](terminal.md).

## Range lifetime

Mission Control ranges have an initial lease, extension increment, and maximum lifetime.
The active page shows remaining time and scheduled cleanup.
Select **Extend by up to N days** when the current policy permits an extension.
The server bounds it by the range generation's maximum expiry.

Defaults are **30 / 30 / 365 days** for initial, increment, and maximum duration.
CTF participant and spare ranges instead use their event cleanup deadline.
Expired ranges enter asynchronous cleanup; billing stops after provider destruction completes.

### Configuring the lease policy

The operator sets the deployment fallback under `settings.mission_control_leases` in `bigrae.yaml`:

```yaml
settings:
  mission_control_leases:
    initial_days: 30
    extension_days: 30
    maximum_days: 365
    extensions_enabled: true
```

All fields are optional and use the defaults above when omitted.
Durations must be positive, and `initial_days` cannot exceed `maximum_days`.
The extension increment can exceed the maximum; each actual extension is bounded by remaining lifetime.
Invalid combinations fail installation validation.

A new generation snapshots its durations and increment.
Later duration changes do not shorten or extend existing generations.
The live `extensions_enabled: false` switch denies further extensions without changing expiry or disabling cleanup.
Setting initial and maximum durations equal only prevents extensions for new generations.

Deployment-fallback changes require the normal process rollout.
Old and new processes can briefly apply different fallback policies during that rollout.
Longer leases increase standing cost and exposure.
Shorter leases can expire during an exercise.

### Runtime tenant and group policy (platform administrators)

You need current `installation.manage_lease_policy` authority and a matching credential ceiling.
Open **Administer > Platform Settings** to inspect fallback and effective runtime policy.

Save the tenant policy to replace all four fields in one revision-checked operation.
**Reset tenant policy** removes the runtime override and restores the deployment fallback.
Reset still advances the revision.
Refresh after a conflict before attempting another edit.

An administrator-controlled Django group policy can further restrict durations.
For multiple matching groups, the lowest initial, increment, and maximum values apply.
Extensions require every matching group and the tenant to allow them.
Group initial and maximum durations cannot exceed the tenant maximum.
CTF teams, provider claims, workspace roles, and the `CTF Participant` group do not select this policy.
A lease group does not grant launch or access permission.

New cold-created and warm-claimed generations use the current durations.
Existing generations keep their snapshots.
The extension switch is checked live.
Each successful change is audited.

## Cancel a range

For **Pending** or **Provisioning**:

1. Open **Ranges**.
2. Select **Cancel launch**.
3. Confirm the cancellation.
4. Wait for the terminal cleanup result.

## Destroy a range

Destruction removes the range's guest data and cannot be reversed.
Preserve approved exercise evidence before you proceed.

1. Open **Ranges**.
2. Verify the range identity.
3. Select **Destroy**.
4. Confirm with **Destroy**.
5. Wait for **Destroyed** and check that no active range remains.

A **Destroying** or unknown result requires continued monitoring or operator recovery.
Do not delete records to simulate cleanup.

## Warm pool for faster initial launch

An operator can enable `settings.warm_pool` to prepare system-owned ranges before an initial launch.
It is disabled by default.
An active policy requires `WARM_POOL_SERVICE_CREDENTIAL_UUID` for an active installation-scoped service admission with `installation.launch_range`.
That UUID is a non-secret reference; the workload authenticates through its keyless service identity.
Startup rejects an invalid reference.

A compatible claim transfers a ready generation with fresh credentials and access.
Previous tenant data and sessions do not cross the ownership boundary.
An empty pool, incompatible request, or unsupported backend falls back to cold provisioning.
Compatibility uses immutable backend, region, scenario/lock digest, purpose, and access inputs.
Changed inputs retire incompatible prepared ranges.

The GCE backend supports warm activation.
AWS and retained GDC paths report it as unsupported and cold-provision instead.
Each bucket declares target, minimum, maximum, and warm idle lifetime.
Warm ranges count against provider capacity and cost admission.
A capacity or cost ceiling can keep the pool below minimum; the reconciler reports the shortfall.

Metrics use `Shifter/WarmPool` for ready, provisioning, unhealthy, claim, fallback, and idle-age observations.
The CTF [recovery-spare pool](ctf-organizer-guide.md#setting-the-spare-pool) is separate.
Recovery spares replace failed participant ranges; warm ranges accelerate initial launches.

## Limits

Mission Control ranges cannot pass their snapshotted maximum expiry.
The default maximum is 365 days.
Warm claims do not establish another backend's release support.
Use the [operation reference](../technical/shifter_platform/retry-safe-range-operations.md) for exact retry and cleanup contracts.
