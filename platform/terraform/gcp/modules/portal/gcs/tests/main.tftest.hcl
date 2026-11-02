# Platform bucket encryption contract test (#2564).
#
# Credential-free: mock_provider synthesizes the google provider. Run with:
#   terraform -chdir=platform/terraform/gcp/modules/portal/gcs test

mock_provider "google" {
  mock_data "google_storage_project_service_account" {
    defaults = {
      member = "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id    = "shifter-test"
  region        = "us-central1"
  environment   = "acme"
  name_prefix   = "shifter-acme"
  common_labels = { managed_by = "terraform" }
}

run "platform_buckets_use_their_own_keys_in_the_bucket_location" {
  command = apply

  assert {
    condition     = module.cmek.key_ids["assets"] == google_storage_bucket.assets.encryption[0].default_kms_key_name
    error_message = "The assets bucket must use its own customer-managed key (#2564)."
  }

  assert {
    condition     = module.cmek.key_ids["audit-logs"] == google_storage_bucket.audit_logs.encryption[0].default_kms_key_name
    error_message = "The audit-log bucket must use its own customer-managed key (#2564)."
  }

  assert {
    condition     = module.cmek.key_ids["assets"] != module.cmek.key_ids["audit-logs"]
    error_message = "Each platform bucket role must have a distinct key (#2564)."
  }

  assert {
    condition     = output.storage_cmek_buckets == { (google_storage_bucket.assets.name) = module.cmek.key_ids["assets"], (google_storage_bucket.audit_logs.name) = module.cmek.key_ids["audit-logs"] }
    error_message = "The module must publish each bucket with its key for the object migration (#2564)."
  }
}
