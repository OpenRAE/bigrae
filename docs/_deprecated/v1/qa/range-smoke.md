# Range Smoke Test

> **Applicability** Historical reference. The text below preserves an earlier description, proposal, or example.
> It is not current operating guidance. An exact source or deployment baseline is not consistently recorded.
> The retained file history alone cannot reproduce that environment.
> See the [current architecture](../../../technical/architecture.md) for present boundaries and supported guidance.

<!-- Preserved source-bound record below. Excluded from Vale to retain original wording and evidence. -->
<!-- vale off -->

## Setup

```bash
# Dev
export ENV=dev AWS_PROFILE=<dev account profile>

# Prod
export ENV=prod AWS_PROFILE=<prod account profile>
```

## CLI Checks (Claude)

```bash
# VPC exists
aws ec2 describe-vpcs --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-vpc" \
  --query 'Vpcs[0].[VpcId,CidrBlock]' --output text

# IGW attached
aws ec2 describe-internet-gateways --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-igw" \
  --query 'InternetGateways[0].InternetGatewayId' --output text

# Security groups
aws ec2 describe-security-groups --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-*" \
  --query 'SecurityGroups[*].[GroupName,GroupId]' --output table
```

<!-- vale on -->
