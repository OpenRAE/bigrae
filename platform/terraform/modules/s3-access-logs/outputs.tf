# Source logging resources reference this output. The dependency on the policy
# makes the delivery grant exist before a source enables logging.
output "bucket" {
  description = "Name of the S3 server access log destination bucket."
  value       = aws_s3_bucket.this.id
  depends_on  = [aws_s3_bucket_policy.this]
}

output "arn" {
  description = "ARN of the S3 server access log destination bucket."
  value       = aws_s3_bucket.this.arn
}

output "source_bucket_names" {
  description = "Buckets that may deliver S3 server access logs to this destination."
  value       = sort(var.source_bucket_names)
}
