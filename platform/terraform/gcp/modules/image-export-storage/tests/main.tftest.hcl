# Image export bucket encryption contract test (#2564).
#
# Credential-free: mock_provider synthesizes the google provider. Run with:
#   terraform -chdir=platform/terraform/gcp/modules/image-export-storage test

mock_provider "google" {
  mock_data "google_storage_project_service_account" {
    defaults = {
      member = "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id                   = "example-build"
  region                       = "us-central1"
  name_prefix                  = "shifter-build"
  packer_service_account_email = "shifterbuild-packer@example-build.iam.gserviceaccount.com"
  access_log_bucket_name       = "example-build-release-evidence"
}

run "export_buckets_use_their_own_keys" {
  command = apply

  assert {
    condition     = module.cmek.key_ids["staging"] == google_storage_bucket.staging.encryption[0].default_kms_key_name
    error_message = "The export staging bucket must use its own customer-managed key (#2564)."
  }

  assert {
    condition     = module.cmek.key_ids["daisy-scratch"] == google_storage_bucket.daisy_export_scratch.encryption[0].default_kms_key_name
    error_message = "The Daisy scratch bucket must use its own customer-managed key (#2564)."
  }

  assert {
    condition     = output.storage_cmek_buckets == { (google_storage_bucket.staging.name) = module.cmek.key_ids["staging"], (google_storage_bucket.daisy_export_scratch.name) = module.cmek.key_ids["daisy-scratch"] }
    error_message = "The module must publish each bucket with its key for the object migration (#2564)."
  }
}
