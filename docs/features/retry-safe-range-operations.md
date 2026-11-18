# Retry-safe range operations

Recover a lost API launch response without creating another range.
You need the same live credential, current authority, and selected scope as an ordinary launch.

## Idempotency-Key header

1. Choose a unique retry key for the intended launch.
2. Send it as `Idempotency-Key` with `POST /api/v1/mission-control/range/launch/`.
3. If the response is lost, repeat the same request with the same key and selections.
4. Read the recovered operation instead of submitting another launch intent.

The first accepted use reports `"recovered": false`.
An identical replay reports `"recovered": true` and returns the original range.
Different selections under the same key return **409 Conflict**.
The key is scoped to the acting principal in one deployment.
It grants no access to another actor's operation.
Current authorization still applies to retries.

### Caller-key rules

A key is limited to **200 characters**.
Leading and trailing whitespace is removed.
An empty or whitespace-only key is treated as absent and gives no idempotency protection.
The retained binding has a bounded retry window.
After that window, reuse can create a new binding.
Do not reuse a key for another launch.

## Truthful cleanup outcomes

Cancel and destroy requests dispatch asynchronous teardown.
A **Destroying** state means resources are still being removed.
Capacity and assignment are released only at verified **Destroyed** state.
A timeout, missing task, failed status, or incomplete evidence remains pending or unknown.
Do not treat it as empty success.

Monitor the original operation and use [range cleanup](ranges.md#destroy-a-range).
See the [technical reference](../technical/shifter_platform/retry-safe-range-operations.md) for exact wire and retention contracts.
