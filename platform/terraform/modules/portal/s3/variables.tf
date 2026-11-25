variable "bucket_name" {
  description = "Name of the S3 bucket (must be globally unique)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "cors_allowed_origins" {
  description = "Origins allowed to make CORS requests (for presigned URL uploads)"
  type        = list(string)
  default     = []
}

variable "kms_key_arn" {
  description = "ARN of the KMS CMK used for SSE-KMS bucket encryption (CKV_AWS_145). Required input — no default. Pair with `bucket_key_enabled` to keep KMS API costs bounded."
  type        = string
}

variable "access_log_bucket" {
  description = "Name of this root's S3 server access log destination (modules/s3-access-logs)."
  type        = string

  validation {
    condition     = length(var.access_log_bucket) > 0
    error_message = "access_log_bucket must name the root's S3 server access log destination."
  }
}
