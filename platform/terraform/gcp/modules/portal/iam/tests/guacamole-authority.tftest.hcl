# Credential-free plan: gateway metadata identity is isolated from cloud workers.
mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      name = "projects/synthetic-project/serviceAccounts/default@synthetic-project.iam.gserviceaccount.com"
    }
  }
}

override_resource {
  target = google_service_account.workload["guacamole-client"]
  values = {
    name      = "projects/synthetic-project/serviceAccounts/gateway@synthetic-project.iam.gserviceaccount.com"
    email     = "gateway@synthetic-project.iam.gserviceaccount.com"
    unique_id = "111111111111111111111"
  }
}

override_resource {
  target = google_service_account.workload["portal"]
  values = {
    name      = "projects/synthetic-project/serviceAccounts/portal@synthetic-project.iam.gserviceaccount.com"
    email     = "portal@synthetic-project.iam.gserviceaccount.com"
    unique_id = "222222222222222222222"
  }
}

variables {
  workload_identity_pool    = "synthetic-project.svc.id.goog"
  project_id                = "synthetic-project"
  dynamic_secret_project_id = "synthetic-project"
  environment               = "test"
  name_prefix               = "shifter-test"
  runtime_secret_ids = {
    app            = "projects/synthetic-project/secrets/synthetic-app"
    db-migration   = "projects/synthetic-project/secrets/synthetic-migration"
    db-provisioner = "projects/synthetic-project/secrets/synthetic-provisioner"
  }
  assets_bucket_name          = "synthetic-assets"
  terraform_state_bucket_name = "synthetic-state"
}

run "guacamole_identity_isolated_from_application_workers" {
  command = plan

  assert {
    condition     = contains(keys(google_service_account.workload), "guacamole-client")
    error_message = "The gateway must have its own Google service account."
  }
  assert {
    condition     = try(google_service_account_iam_member.workload_identity["guacamole-client"].member == "serviceAccount:synthetic-project.svc.id.goog[shifter-platform/guacamole-client]", false)
    error_message = "Only the dedicated gateway Kubernetes identity may use its Google identity."
  }
  assert {
    condition     = try(length(local.workload_project_roles["guacamole-client"]) == 0, false)
    error_message = "Gateway renewal needs no project-level cloud role."
  }
  assert {
    condition     = alltrue([for binding in values(local.workload_secret_bindings) : binding.workload != "guacamole-client"])
    error_message = "The gateway must not inherit platform runtime-secret access."
  }
}

run "controller_output_uses_exact_gateway_identity" {
  command = apply
  assert {
    condition = (
      output.guacamole_controller_identity.email == "gateway@synthetic-project.iam.gserviceaccount.com" &&
      output.guacamole_controller_identity.unique_id == "111111111111111111111"
    )
    error_message = "Gateway control must use the gateway's email and immutable subject, never the portal identity."
  }
}
