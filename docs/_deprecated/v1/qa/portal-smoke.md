# Portal Smoke Test

> **Applicability** Historical reference. The text below preserves an earlier description, proposal, or example.
> It is not current operating guidance. An exact source or deployment baseline is not consistently recorded.
> The retained file history alone cannot reproduce that environment.
> See the [current architecture](../../../technical/architecture.md) for present boundaries and supported guidance.

<!-- Preserved source-bound record below. Excluded from Vale to retain original wording and evidence. -->
<!-- vale off -->

## Setup

```bash
# Dev
export ENV=dev DOMAIN=dev.shifter.example.com AWS_PROFILE=<dev account profile>

# Prod
export ENV=prod DOMAIN=shifter.example.com AWS_PROFILE=<prod account profile>
```

## CLI Checks (Claude)

```bash
# Health
curl -sf "https://${DOMAIN}/health/" && echo "OK" || echo "FAIL"

# EC2 running
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-portal-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text
```

## Browser Checks (You)

1. Open `https://${DOMAIN}/`
2. Cognito redirect → login
3. Dashboard loads

<!-- vale on -->
