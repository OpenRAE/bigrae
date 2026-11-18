# Set Up NGFW Demo

Use this how-to guide to provision and check an NGFW on a configured deployment.
This procedure creates billable cloud resources and uses Software NGFW Credits.

## Before You Start

You need:

- Current application authority for the selected scope and NGFW operations.
- Cloud capacity and approval for the compute, storage, and license costs.
- A Software NGFW Credits deployment profile and its authcode.
- SCM access, an onboarding folder, and a registration PIN id and value.
- Your licensing region and, if used, access to XDR or XSIAM.

Use existing approved SCM and XDR/XSIAM services.
Do not send credentials to another service or include them in logs or support records.
The earlier timing estimate was about 45 minutes, including 15–30 minutes for provisioning.
These estimates are not current deployment qualification or a timeout guarantee.

The current SPA uses credential identifiers instead of credential pickers.
It has no **Complete Setup** control.
External console labels and account-specific integration have not been verified by this source-only review.

## Step 1: Add Deployment Profile Credential

1. Open **Credentials** at `/mission-control/credentials/`.
2. Select **Deployment Profile** under **Credential type**.
3. Enter a **Display name** and the **VM-Series authcode**.
4. Set an expiration date when required by your policy.
5. Select **Save credential**.
6. Record the returned credential id, without copying the authcode.

The current page creates credentials and displays the new id.
It does not provide a credential inventory picker.

## Step 2: Add SCM Credential

1. Open **Credentials** again.
2. Select **SCM Registration**.
3. Enter the display name, **Folder name**, **PIN id**, **PIN value**, and **Licensing region**.
4. Select **Save credential**.
5. Record its returned id.

### Where to Get These Values

Obtain the folder and registration PIN from your authorized SCM administrator.
Use the region assigned to your licensing and logging configuration.
Console navigation can change; confirm it against the selected SCM version.
Keep the PIN value and authcode private.

## Step 3: Provision the NGFW

1. Open **NGFWs** at `/mission-control/ngfws/`.
2. Select **Set up NGFW**.
3. Enter the **NGFW name**.
4. Enter the **Deployment profile credential id** from step 1.
5. Enter the **SCM credential id** from step 2.
6. Review the target, credential ids, and costs.
7. Select **Provision NGFW** once.
8. Read the resulting NGFW status and serial number on its detail page.

Credential ids identify stored inputs; they are not the secret values.
A failed or slow request does not prove that no cloud resource was created.
Inspect the recorded resource and operation before retrying.

## Step 4: Associate Device in SCM

The provisioning request uses the stored SCM registration PIN.
Read the serial number from the NGFW detail page when it becomes available.
If SCM requires an external association, follow its approved onboarding procedure for that serial number and folder.
Do not submit duplicate provisioning requests to obtain another serial number.
A console association alone does not prove that BigRAE provisioning completed.

## Step 5: Connect to XDR/XSIAM

Use your approved XDR or XSIAM integration procedure for the selected firewall and logging service.
Confirm licensing, account scope, log forwarding, and the actual integration status in those services.
BigRAE source inspection does not verify their console workflow or delivery.
Keep this step separate from application readiness and range cleanup checks.

## Step 6: Confirm NGFW Readiness { #step-6-complete-setup-in-bigrae }

The current SPA detail page shows status, serial number, creation time, CLI access when ready, and deprovisioning.
It has no **Complete Setup** button or four-stage progress wizard.
Those controls belonged to the earlier interface.
Wait for the recorded status to become **Ready**.
If it does not, follow the investigation steps below.
The earlier final-configuration estimate of up to 15 minutes is historical, not a current completion gate.

## Step 7: Access NGFW management {#step-7-access-ngfw-management-optional}

Use the [NGFW CLI procedure](../features/ngfw.md#accessing-ngfw-management) for the ready firewall.
The current detail page provides **Open CLI**.
It does not establish a local SSH tunnel or a general GUI session.
Ask the operator for any separate management-network procedure.

## Step 8: Launch an NGFW-enabled range {#step-8-launch-ngfw-enabled-range}

Confirm the installed pack and backend support before launch.
The GCE range-cell path does not support the retained NGFW attachment contract.
A standalone ready firewall does not supply that missing capability.

1. Open **Ranges > Launch a range**.
2. Select the approved workspace and compatible installed scenario.
3. Select the required installer.
4. Select **Launch range**.
5. Inspect the operation result before connecting.
6. Follow [range cleanup](../features/ranges.md#destroy-a-range) after the exercise.

The operator owns firewall setup, routing verification, and persistent-firewall cleanup.

## Verifying the Setup

Confirm each boundary separately:

- BigRAE reports the intended NGFW ready with the expected serial number.
- Approved CLI access reaches that firewall.
- The selected range uses the intended route and policy.
- SCM receives the expected firewall state and logs.
- XDR/XSIAM receives the expected network records, if configured.
- Range teardown removes range-owned resources without deleting the persistent NGFW.

For PAN-OS inspection, use the commands supported by the installed version.
Earlier examples were `show traffic`, `show running security-policy-match`, and `show session all`.
Their applicability has not been verified against a running PAN-OS release here.
Generate only an approved synthetic traffic sample.
An endpoint alert alone does not prove network-log delivery.

## Troubleshooting

Record the request id, NGFW id, status, serial number, source revision, and last bounded error.
Keep authcodes, PIN values, tokens, user content, and raw provider payloads out of support records.

- **Provisioning is slow:** check cloud operation state, capacity, licensing, and stored credential metadata.
  The earlier guidance used 30 minutes for investigation and 45 minutes for escalation.
  Use the actual operation deadline; do not deprovision solely because an estimate elapsed.
- **SCM association fails:** confirm the exact serial number, folder authority, and PIN validity with the SCM owner.
- **CLI access fails:** confirm the NGFW is ready and use [RB019](../runbooks/rb019-check-system-health.md).
- **Network alerts are absent:** check firewall log generation, forwarding, SCM ingestion, and XDR/XSIAM ingestion separately.
- **Range launch fails:** check the selected scenario, NGFW state, and authorized lifecycle operation.

For cleanup, select **Deprovision NGFW** on its detail page only after owner approval and dependency review.
The dialog describes destructive removal and license deactivation.
The action cannot be undone.
Verify terminal operation state, absent provider resources, and license disposition before reporting cleanup.
Retain credentials while accepted cleanup still needs them; remove them afterward through their owning service.
