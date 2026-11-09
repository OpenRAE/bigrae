# QA Smoke Tests

> **Applicability** Historical reference. The text below preserves an earlier description, proposal, or example.
> It is not current operating guidance. An exact source or deployment baseline is not consistently recorded.
> The retained file history alone cannot reproduce that environment.
> See the [current architecture](../../../technical/architecture.md) for present boundaries and supported guidance.

<!-- Preserved source-bound record below. Excluded from Vale to retain original wording and evidence. -->
<!-- vale off -->

Standardized smoke test protocols for verifying Shifter deployments.

## When to Run

| Trigger | Tests to Run |
|---------|--------------|
| First deploy to new environment | [Dev Deploy Checklist](dev-deploy-smoke.md) |
| After infrastructure changes | Module-specific test for changed component |
| After application deploy | [Portal](portal-smoke.md) |
| Before releases | All smoke tests |
| Provisioner changes | [Provisioner](provisioner-smoke.md) (includes create + teardown) |

## Test Matrix

| Module | Test File | Time | Prerequisites |
|--------|-----------|------|---------------|
| Portal | [portal-smoke.md](portal-smoke.md) | 2 min | Portal deployed, DNS configured |
| Range | [range-smoke.md](range-smoke.md) | 1 min | Range VPC deployed |
| Provisioner | [provisioner-smoke.md](provisioner-smoke.md) | 5 min | Portal + Range deployed |
| Dev Deploy | [dev-deploy-smoke.md](dev-deploy-smoke.md) | 15 min | Fresh environment |

## Environment Selection

All tests should specify which environment they're targeting:

```bash
# Set environment
export ENV=dev  # or prod
export AWS_PROFILE=panw-shifter-${ENV}-workstation
```

## Pass/Fail Criteria

- **Pass**: All checks complete without errors
- **Fail**: Any check returns unexpected result or error

Document failures in the issue tracker with:
1. Environment (dev/prod)
2. Which check failed
3. Error output
4. Timestamp

<!-- vale on -->
