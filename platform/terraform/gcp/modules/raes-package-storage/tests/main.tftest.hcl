# Private pack bucket encryption contract test (#2564).
#
# Credential-free: mock_provider synthesizes the google provider. Run with:
#   terraform -chdir=platform/terraform/gcp/modules/raes-package-storage test

mock_provider "google" {
  mock_data "google_storage_project_service_account" {
    defaults = {
      member = "serviceAccount:service-123@gs-project-accounts.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id                   = "example-tenant"
  bucket_name                  = "example.tenant-packs"
  location                     = "US-CENTRAL1"
  access_log_bucket_name       = "example-tenant-audit-logs"
  portal_service_account_email = "portal@example-tenant.iam.gserviceaccount.com"
}

run "pack_bucket_uses_its_own_key_in_the_bucket_location" {
  command = apply

  assert {
    condition     = module.cmek.key_ids["raes-packages"] == google_storage_bucket.packages.encryption[0].default_kms_key_name
    error_message = "The pack bucket must use its own customer-managed key (#2564)."
  }

  assert {
    condition     = module.cmek.key_ring_location == lower(google_storage_bucket.packages.location)
    error_message = "The pack key ring must be in the bucket location (#2564)."
  }

  assert {
    condition     = output.package_bucket_kms_key == module.cmek.key_ids["raes-packages"]
    error_message = "The module must publish the key for gcp-cmek-migrate (#2564)."
  }
}

run "multi_region_pack_bucket" {
  command = apply

  variables {
    location = "US"
  }

  assert {
    condition     = module.cmek.key_ring_location == "us"
    error_message = "A multi-region pack bucket needs a multi-region key ring (#2564)."
  }
}
