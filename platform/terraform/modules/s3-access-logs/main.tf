# ------------------------------------------------------------------------------
# S3 server access log destination for one Terraform root (#2566)
# ------------------------------------------------------------------------------
# AWS requires the destination in the source account and Region, with SSE-S3
# default encryption and no server access logging of its own. Each source bucket
# writes only under its own prefix. Ownership is bucket-owner-enforced, so the
# grant is a bucket policy, not an ACL.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

# AWS documents that a destination bucket must not have server access logging,
# so this bucket is the terminal sink. See docs/adr/exceptions.yaml.
#trivy:ignore:AWS-0089:exp:2027-11-25
resource "aws_s3_bucket" "this" {
  # checkov:skip=CKV_AWS_145:S3 server access log delivery supports only SSE-S3 on the destination bucket. See ADR-004-R11 exception s3-access-log-destination.
  # checkov:skip=CKV_AWS_18:AWS documents that a server access log destination must not have server access logging. See ADR-004-R11 exception s3-access-log-destination.
  bucket = "${var.name_prefix}-s3-access-logs-${local.account_id}"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-s3-access-logs"
  })
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

# S3 server access log delivery supports only SSE-S3 on the destination.
#trivy:ignore:AWS-0132:exp:2027-11-25
resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  # Versioning must be on before noncurrent rules apply.
  depends_on = [aws_s3_bucket_versioning.this]

  rule {
    id     = "access-log-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = var.retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "expired-delete-markers"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }
  }
}

locals {
  deny_insecure_transport = {
    Sid       = "DenyInsecureTransport"
    Effect    = "Deny"
    Principal = "*"
    Action    = "s3:*"
    Resource  = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }

  # One grant for each source: the source may write only its own prefix.
  log_delivery = [
    for name in sort(var.source_bucket_names) : {
      Sid       = "S3ServerAccessLogs${substr(sha256(name), 0, 12)}"
      Effect    = "Allow"
      Principal = { Service = "logging.s3.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.this.arn}/${name}/*"
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:s3:::${name}" }
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }
  ]
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([local.deny_insecure_transport], local.log_delivery) })

  # Apply the public-access block and ownership first.
  depends_on = [
    aws_s3_bucket_public_access_block.this,
    aws_s3_bucket_ownership_controls.this,
  ]
}
