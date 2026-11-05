mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012" }
  }
  mock_resource "google_service_account" {
    defaults = {
      email = "other-workload@synthetic-project.iam.gserviceaccount.com"
      name  = "projects/synthetic-project/serviceAccounts/other-workload@synthetic-project.iam.gserviceaccount.com"
    }
  }
}

override_resource {
  target = google_service_account.workload["provisioner"]
  values = {
    email = "provisioner@synthetic-project.iam.gserviceaccount.com"
    name  = "projects/synthetic-project/serviceAccounts/provisioner@synthetic-project.iam.gserviceaccount.com"
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

run "registered_project_writes_stay_in_their_owned_prefixes" {
  command = apply

  assert {
    condition     = toset(keys(google_storage_bucket_iam_member.registered_project_storage)) == toset(["baselines", "state"])
    error_message = "Registered projects need only baseline and state storage grants."
  }
  assert {
    condition = alltrue([for grant in google_storage_bucket_iam_member.registered_project_storage :
      grant.bucket == "synthetic-assets" &&
      grant.member == "serviceAccount:provisioner@synthetic-project.iam.gserviceaccount.com"
    ])
    error_message = "Only the provisioner may write registered-project objects in the configured assets bucket."
  }
  assert {
    condition = (
      google_storage_bucket_iam_member.registered_project_storage["baselines"].role == "roles/storage.objectCreator" &&
      google_storage_bucket_iam_member.registered_project_storage["baselines"].condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/synthetic-assets/objects/raes/project-baselines/\")"
    )
    error_message = "Baseline access must allow creation only under the baseline prefix, without overwrite or delete."
  }
  assert {
    condition = (
      google_storage_bucket_iam_member.registered_project_storage["state"].role == "roles/storage.objectUser" &&
      google_storage_bucket_iam_member.registered_project_storage["state"].condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/synthetic-assets/objects/raes/project-state/\")"
    )
    error_message = "State and lock access must stay under the state prefix, without bucket or IAM administration."
  }
  assert {
    condition = (
      local.workload_bucket_bindings["provisioner:assets"].role == "roles/storage.objectViewer" &&
      local.workload_bucket_bindings["provisioner:state"].bucket == "synthetic-state"
    )
    error_message = "Other assets stay read-only and the existing range state bucket stays separate."
  }
}
