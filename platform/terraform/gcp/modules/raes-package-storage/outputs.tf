output "package_bucket" {
  value       = google_storage_bucket.packages.name
  description = "Set SHIFTER_RAES_PACKAGE_BUCKET in the existing tenant runtime configuration."
}

output "package_bucket_kms_key" {
  value       = module.cmek.key_ids["raes-packages"]
  description = "Customer-managed key of the pack bucket; pass it to deploy.py gcp-cmek-migrate (#2564)."
}
