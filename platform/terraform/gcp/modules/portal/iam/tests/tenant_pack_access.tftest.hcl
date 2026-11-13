# Deploy bootstrap assesses installed tenant packs as the migrator. Its archive
# read grant follows the selected package store and never opens unrelated assets.
mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012" }
  }
  mock_resource "google_service_account" {
    defaults = {
      email = "synthetic-runtime@synthetic-project.iam.gserviceaccount.com"
      name  = "projects/synthetic-project/serviceAccounts/synthetic-runtime@synthetic-project.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id                  = "synthetic-project"
  dynamic_secret_project_id   = "synthetic-project"
  environment                 = "test"
  name_prefix                 = "shifter-test"
  workload_identity_pool      = "synthetic-project.svc.id.goog"
  assets_bucket_name          = "synthetic-assets"
  terraform_state_bucket_name = "synthetic-state"
  runtime_secret_ids = {
    app            = "projects/synthetic-project/secrets/app"
    db             = "projects/synthetic-project/secrets/db"
    db-migration   = "projects/synthetic-project/secrets/migrate"
    db-provisioner = "projects/synthetic-project/secrets/provisioner"
    guacamole-db   = "projects/synthetic-project/secrets/guacamole"
  }
}

run "assets_package_store_limits_migrator_to_tenant_packs" {
  command = plan

  assert {
    condition     = google_storage_bucket_iam_member.migrator_tenant_packs.bucket == "synthetic-assets"
    error_message = "The default package store must be the deployment assets bucket."
  }
  assert {
    condition     = google_storage_bucket_iam_member.migrator_tenant_packs.role == "roles/storage.objectViewer"
    error_message = "The migrator needs read-only object access."
  }
  assert {
    condition     = google_storage_bucket_iam_member.migrator_tenant_packs.condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/synthetic-assets/objects/tenant-packs/\")"
    error_message = "The assets grant must expose only installed tenant pack archives."
  }
}

run "dedicated_package_store_keeps_the_same_prefix_boundary" {
  command = plan

  variables {
    raes_package_bucket_name = "synthetic-packages"
  }

  assert {
    condition     = google_storage_bucket_iam_member.migrator_tenant_packs.bucket == "synthetic-packages"
    error_message = "A dedicated package store must own the migrator grant."
  }
  assert {
    condition     = google_storage_bucket_iam_member.migrator_tenant_packs.condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/synthetic-packages/objects/tenant-packs/\")"
    error_message = "The dedicated-bucket grant must remain limited to tenant packs."
  }
}
