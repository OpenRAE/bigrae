# Credentials

Store an SCM registration credential or software NGFW deployment profile.
These integration credentials are separate from [platform access credentials](access-credentials.md).
You need current content-management authority for the destination scope.

## When you need credentials

Use these credentials only when an approved integration or scenario requires them.
The Linux smoke tutorial does not require an NGFW credential.
Ask the operator to confirm backend compatibility before preparing firewall resources.

## Credential types

### SCM credentials

The current **SCM Registration** form uses these fields:

| Field | Purpose |
| --- | --- |
| Folder name | SCM device registration destination |
| PIN id | Registration PIN identifier |
| PIN value | Secret registration value |
| Licensing region | Americas, Europe, Japan, or Asia Pacific |

### Deployment profiles

The **Deployment Profile** form takes the secret **VM-Series authcode**.
Use an approved licensing source.
Keep authcodes and PIN values out of logs, URLs, screenshots, and public issues.

## Add credentials

1. Open **Assets > Credentials**.
2. Select **Credential type**.
3. Enter a **Display name**.
4. Enter the type-specific values.
5. Enter **Expiration date** when applicable.
6. Select **Save credential**.
7. Record the returned identifier in the approved operational record.

The NGFW setup form needs that identifier.
The confirmation does not reveal the secret again.
Correct any validation error before another submission.

## Expiration

The credential accepts an optional expiration date.
Confirm renewal requirements with the licensing or SCM owner.
The current page does not provide a list with expiration badges.

## Manage credentials

The SPA currently creates credentials but does not list existing ones.
Immediately after creation, **Delete this credential** removes that created credential after confirmation.
For another stored credential, use the operator's supported administration procedure.
Deletion cannot be undone.

## Where to get these values

Obtain SCM registration values from your authorized SCM administrator.
Obtain the deployment profile authcode from your approved licensing portal or account contact.
Use the [operator NGFW guide](../how-to/ngfw-demo.md) for provisioning and association.
