# GCS customer-managed key contract test (#2564).
#
# Credential-free: mock_provider synthesizes the google provider. Run with:
#   terraform -chdir=platform/terraform/gcp/modules/gcs-cmek test

mock_provider "google" {
  mock_data "google_storage_project_service_account" {
    defaults = {
      email_address = "service-123@gs-project-accounts.iam.gserviceaccount.com"
      member        = "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id    = "shifter-test"
  location      = "US-CENTRAL1"
  key_ring_name = "shifter-test-gcs"
  key_names     = ["assets", "audit-logs"]
  labels        = { managed_by = "terraform" }
}

run "each_bucket_role_gets_a_rotating_key_in_the_bucket_location" {
  command = plan

  assert {
    condition     = google_kms_key_ring.this.location == "us-central1" && google_kms_key_ring.this.project == "shifter-test"
    error_message = "The key ring must be in the lowercase bucket location and the bucket project (#2564)."
  }

  assert {
    condition     = toset(keys(google_kms_crypto_key.keys)) == toset(["assets", "audit-logs"])
    error_message = "Each bucket role must have its own key (#2564)."
  }

  assert {
    condition     = alltrue([for key in google_kms_crypto_key.keys : key.rotation_period == "7776000s" && key.purpose == "ENCRYPT_DECRYPT"])
    error_message = "Each key must be a symmetric key that rotates every 90 days (#2564)."
  }
}

run "only_the_bucket_project_storage_agent_can_use_each_key" {
  command = plan

  assert {
    condition     = toset(keys(google_kms_crypto_key_iam_member.storage_agent)) == toset(["assets", "audit-logs"])
    error_message = "Each key must grant the Storage service agent (#2564)."
  }

  assert {
    condition = alltrue([
      for grant in google_kms_crypto_key_iam_member.storage_agent :
      grant.role == "roles/cloudkms.cryptoKeyEncrypterDecrypter" && grant.member == "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
    ])
    error_message = "Only the bucket project's Storage service agent may encrypt and decrypt with the key (#2564)."
  }

  assert {
    condition     = data.google_storage_project_service_account.this.project == "shifter-test"
    error_message = "The Storage service agent must belong to the bucket project (#2564)."
  }
}

run "multi_region_bucket_uses_the_multi_region_key_location" {
  command = plan

  variables {
    location = "US"
  }

  assert {
    condition     = google_kms_key_ring.this.location == "us"
    error_message = "A multi-region bucket needs its key ring in the same multi-region (#2564)."
  }
}

run "a_bucket_role_is_required" {
  command = plan

  variables {
    key_names = []
  }

  expect_failures = [var.key_names]
}
