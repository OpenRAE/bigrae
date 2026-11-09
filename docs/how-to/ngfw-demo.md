# Set Up NGFW Demo

Complete walkthrough: add credentials, provision NGFW, associate in SCM, launch NGFW-enabled range.

## Before You Start

You need:

- Access to Strata Cloud Manager (SCM)
- Access to your XDR or XSIAM console
- Software NGFW Credits deployment profile with authcode
- SCM folder configured for device onboarding

Time: ~45 minutes (mostly waiting for provisioning)

## Step 1: Add Deployment Profile Credential

The deployment profile contains the authcode that licenses your NGFW.

1. Go to **Assets > Credentials** in BigRAE
2. Click **Add Credential**
3. Select **Deployment Profile**
4. Enter:

   - **Name**: Something descriptive (for example "Lab NGFW License")
   - **Authcode**: Your Software NGFW Credits authcode
5. Save

## Step 2: Add SCM Credential

The SCM credential enables automatic device registration.

1. Go to **Assets > Credentials**
2. Click **Add Credential**
3. Select **SCM Credential**
4. Enter:

   - **Name**: Descriptive name
   - **SCM Folder**: The folder in SCM where the device will register
   - **PIN ID**: Auto-registration PIN from SCM
   - **SLS Region**: Your Strata Logging Service region
5. Save

### Where to Get These Values

- **SCM Folder**: In SCM, go to Configuration > NGFW and Prisma Access > Folders.
- **PIN ID**: In SCM, go to Configuration > Device Associations > Get PIN.
- **SLS Region**: Check your SCM dashboard or account settings.

## Step 3: Provision the NGFW

1. Go to **Assets > NGFWs**
2. Click **Setup NGFW**
3. **Step 1 - Name & Profile**:

   - Enter a name for the NGFW
   - Select your deployment profile
   - Click Next
4. **Step 2 - Registration**:

   - Select your SCM credential
   - Click Next
5. **Step 3 - Confirm**:

   - Review settings
   - Click **Provision NGFW**
6. **Step 4 - Provisioning**:

   - Wait 15-30 minutes
   - Watch the progress steps

## Step 4: Associate Device in SCM

When provisioning reaches "Action Required":

1. Note the **Serial Number** shown in BigRAE
2. Go to **Strata Cloud Manager**
3. Navigate to **Configuration > Device Associations**
4. Click **Add Device**
5. Enter the serial number
6. Associate to your folder

## Step 5: Connect to XDR/XSIAM

1. Go to your **XDR or XSIAM console**
2. Navigate to **Settings > NGFW**
3. Click **Add New Instance**
4. Follow the prompts to connect the firewall

## Step 6: Complete Setup in BigRAE

1. Return to BigRAE's NGFW wizard
2. Click **Complete Setup**
3. Wait for final configuration (up to 15 minutes)
4. Success message appears when ready

## Step 7: Access NGFW management {#step-7-access-ngfw-management-optional}

Use the [NGFW CLI procedure](../features/ngfw.md#accessing-ngfw-management) for the ready firewall.
The current detail page provides **Open CLI**.
It does not establish a local SSH tunnel or a general GUI session.
Ask the operator for any separate management-network procedure.

## Step 8: Launch an NGFW-enabled range

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

**On the NGFW (via CLI):**

- Click **Open CLI** from the NGFW detail page
- Check traffic logs: `show traffic`
- View security policies: `show running security-policy-match`
- Monitor sessions: `show session all`

**In your range:**

- Traffic between attacker and victim routes through NGFW
- Run attacks from Kali terminal

**In XDR/XSIAM:**

- You should see both:
  - Endpoint alerts from your agent
  - Network alerts from NGFW logs
- Alerts correlate attack activity across sources

## Troubleshooting

**NGFW stuck provisioning?**
- Check that your authcode is valid
- Ensure SCM credentials are correct
- Try deprovisioning and starting over

**Device will not associate in SCM?**
- Verify the serial number matches
- Check that the SCM folder allows new devices
- Ensure PIN has not expired

**No network alerts in XDR/XSIAM?**
- Verify NGFW shows as connected in XDR/XSIAM settings
- Check log forwarding is configured in SCM
- Use **Open CLI** to verify traffic is passing through: `show traffic`
- Generate approved traffic that the test expects to log

**Range launch fails with NGFW?**
- Ensure NGFW status is "Ready" before launching
- Check that NGFW was not deprovisioned
