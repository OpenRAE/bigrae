# Audit and activity history

Use this guide to find recorded administrative actions.
The audit ledger is installation-wide because historical rows do not have a reliable customer scope.
A workspace selection does not restrict that ledger.

## Access

You need current `installation.read_audit` authority and a credential that permits that action.
The mounted API accepts the supported session or native bearer authentication.
Staff status, membership, and organization ownership alone do not grant access.
The server checks authorization before it filters or returns rows.

## What it shows

Each row identifies the recorded time, action, entity, and actor.
The history contains events that the owning features recorded.
An absent row is not proof that an operation never occurred.

## Filtering

1. Open **Administer > Audit** or **Audit history** under **Administer > Platform**.
2. Select the required action and entity filters.
3. Enter actor or entity identifiers when needed.
4. Set **From** and **To** with the start no later than the end.
5. Apply the filters.

The page address retains the filters.
Share that address only with an authorized recipient.
It does not grant access to the history.
Invalid filter input must be corrected before the request succeeds.

## Event details

Expand a row to inspect its recorded details.
These can include request identifiers, source addresses, and previous and new values.
Treat the details as sensitive operational evidence.
Do not copy them into a public issue or screenshot without an approved redaction review.

## Related administration

Use the policy-aware Django admin only when your current authority permits the required inspection.
See [account administration reference](../technical/shifter_platform/account-administration.md) for the API and policy boundary.
