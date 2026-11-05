output "key_ids" {
  description = "Key resource name for each bucket role. A bucket that reads it waits for the Storage service agent grant."
  value       = { for name, key in google_kms_crypto_key.keys : name => key.id }
  depends_on  = [google_kms_crypto_key_iam_member.storage_agent]
}

output "key_ring_location" {
  description = "Cloud KMS location of the key ring."
  value       = google_kms_key_ring.this.location
}
