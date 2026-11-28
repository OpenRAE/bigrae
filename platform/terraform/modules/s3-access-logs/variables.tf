variable "name_prefix" {
  description = "Prefix for the destination bucket name."
  type        = string
}

variable "source_bucket_names" {
  description = "Names of the buckets in this root that deliver S3 server access logs here. Each source writes under the prefix <name>/."
  type        = list(string)

  validation {
    condition     = length(var.source_bucket_names) > 0 && alltrue([for name in var.source_bucket_names : can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", name))])
    error_message = "source_bucket_names must list at least one valid S3 bucket name."
  }
}

variable "retention_days" {
  description = "Days to keep current access-log objects."
  type        = number

  validation {
    condition     = var.retention_days >= 1
    error_message = "retention_days must be at least 1."
  }
}

variable "noncurrent_version_expiration_days" {
  description = "Days to keep a replaced or deleted access-log object version."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_expiration_days >= 1
    error_message = "noncurrent_version_expiration_days must be at least 1."
  }
}

variable "tags" {
  description = "Tags for the destination bucket."
  type        = map(string)
  default     = {}
}
