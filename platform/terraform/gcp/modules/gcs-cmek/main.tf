# Customer-managed keys for the GCS buckets of one owner in one location (#2564).
#
# The key ring is in the bucket location: regions, multi-regions, and predefined
# dual-regions have Cloud KMS locations of the same name. Each bucket role has
# its own key. KMS can not delete a key ring, and prevent_destroy blocks a plan
# that deletes a key; the owner removes both from state before a teardown.

# The data source gets the Storage service agent of the bucket project and
# creates it when it does not exist yet.
data "google_storage_project_service_account" "this" {
  project = var.project_id
}

resource "google_kms_key_ring" "this" {
  project  = var.project_id
  name     = var.key_ring_name
  location = lower(var.location)
}

resource "google_kms_crypto_key" "keys" {
  for_each        = toset(var.key_names)
  name            = each.key
  key_ring        = google_kms_key_ring.this.id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s"
  labels          = var.labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "storage_agent" {
  for_each      = google_kms_crypto_key.keys
  crypto_key_id = each.value.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = data.google_storage_project_service_account.this.member
}
