mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    partition = "aws"
  }
}

# AWS sets a bucket's id to its name.
override_resource {
  target = aws_s3_bucket.this
  values = {
    id  = "test-s3-access-logs-123456789012"
    arn = "arn:aws:s3:::test-s3-access-logs-123456789012"
  }
}

variables {
  name_prefix         = "test"
  source_bucket_names = ["test-uploads", "test-logs"]
  retention_days      = 90
}

run "destination_meets_the_s3_server_access_log_contract" {
  command = apply

  assert {
    condition = (
      aws_s3_bucket.this.bucket == "test-s3-access-logs-123456789012" &&
      aws_s3_bucket_ownership_controls.this.rule[0].object_ownership == "BucketOwnerEnforced" &&
      aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled" &&
      one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256" &&
      aws_s3_bucket_public_access_block.this.block_public_acls &&
      aws_s3_bucket_public_access_block.this.block_public_policy &&
      aws_s3_bucket_public_access_block.this.ignore_public_acls &&
      aws_s3_bucket_public_access_block.this.restrict_public_buckets
    )
    error_message = "The destination must use SSE-S3, owner-enforced objects, versioning, and a full public-access block."
  }

  assert {
    condition = (
      contains([for rule in aws_s3_bucket_lifecycle_configuration.this.rule : rule.expiration[0].days if length(rule.expiration) > 0 && rule.expiration[0].days != null], 90) &&
      contains([for rule in aws_s3_bucket_lifecycle_configuration.this.rule : rule.noncurrent_version_expiration[0].noncurrent_days if length(rule.noncurrent_version_expiration) > 0], 30) &&
      contains([for rule in aws_s3_bucket_lifecycle_configuration.this.rule : rule.expiration[0].expired_object_delete_marker if length(rule.expiration) > 0 && rule.expiration[0].expired_object_delete_marker != null], true)
    )
    error_message = "Log objects, noncurrent versions, and expired delete markers must expire."
  }

  assert {
    condition = alltrue([
      for name in ["test-uploads", "test-logs"] : anytrue([
        for statement in jsondecode(aws_s3_bucket_policy.this.policy).Statement :
        statement.Effect == "Allow" &&
        statement.Principal == { Service = "logging.s3.amazonaws.com" } &&
        statement.Action == "s3:PutObject" &&
        statement.Resource == "arn:aws:s3:::test-s3-access-logs-123456789012/${name}/*" &&
        statement.Condition.ArnLike["aws:SourceArn"] == "arn:aws:s3:::${name}" &&
        statement.Condition.StringEquals["aws:SourceAccount"] == "123456789012"
      ])
    ])
    error_message = "Each source bucket may write only its own prefix, from this account."
  }

  assert {
    condition = length([
      for statement in jsondecode(aws_s3_bucket_policy.this.policy).Statement :
      statement if statement.Effect == "Allow"
    ]) == 2
    error_message = "The policy must grant log delivery only for the declared source buckets."
  }

  assert {
    condition = anytrue([
      for statement in jsondecode(aws_s3_bucket_policy.this.policy).Statement :
      statement.Effect == "Deny" && statement.Condition.Bool["aws:SecureTransport"] == "false"
    ])
    error_message = "The destination must refuse requests without TLS."
  }

  assert {
    condition     = output.bucket == "test-s3-access-logs-123456789012"
    error_message = "The module must output the destination bucket name."
  }
}

run "rejects_an_empty_source_list" {
  command = plan

  variables {
    source_bucket_names = []
  }

  expect_failures = [var.source_bucket_names]
}
