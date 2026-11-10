# Provisioner Smoke Test

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


# Lambda functions exist
aws lambda list-functions --profile $AWS_PROFILE --region us-east-2 \
  --query "Functions[?contains(FunctionName, '${ENV}-portal')].FunctionName" --output table
```

## Range Lifecycle Test

### You: Launch range from Portal UI

Note the range_id: ___

### Claude: Verify resources

```bash
RANGE_ID=XXX

# Check EC2s
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Reservations[].Instances[].[Tags[?Key==`Name`].Value|[0],State.Name,PrivateIpAddress]' --output table

# Check subnet
aws ec2 describe-subnets --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[0].[SubnetId,CidrBlock]' --output text
```

### You: Teardown range from Portal UI

### Claude: Verify cleanup

```bash
# Should show terminated or empty
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text

# Should be empty
aws ec2 describe-subnets --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[].SubnetId' --output text
```

<!-- vale on -->
