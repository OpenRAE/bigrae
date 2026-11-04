variable "project_id" {
  description = "Project of the buckets and of their keys."
  type        = string
}

variable "location" {
  description = "Location of the buckets, for example us-central1 or US."
  type        = string
}

variable "key_ring_name" {
  description = "Key ring name, unique in the project and location."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,63}$", var.key_ring_name))
    error_message = "key_ring_name must have 1 to 63 letters, digits, underscores, or hyphens."
  }
}

variable "key_names" {
  description = "One key name for each bucket role."
  type        = list(string)

  validation {
    condition     = length(var.key_names) > 0 && alltrue([for name in var.key_names : can(regex("^[A-Za-z0-9_-]{1,63}$", name))])
    error_message = "key_names must name at least one key; each name has 1 to 63 letters, digits, underscores, or hyphens."
  }
}

variable "labels" {
  description = "Labels of the keys."
  type        = map(string)
  default     = {}
}
