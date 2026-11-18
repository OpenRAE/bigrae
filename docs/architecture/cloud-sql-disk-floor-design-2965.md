# Cloud SQL disk floor design (#2965)

Status: accepted design for issue #2965.
No formal requirement is attached.

## Problem

The capacity profile sets a minimum Cloud SQL disk size.
The `portal/cloud-sql` module ignored changes to `settings[0].disk_size`.
Thus a larger profile did not grow the disk of an existing instance.
PD-SSD performance increases with disk size, so a small disk limits the database.

## Decision

Terraform manages `disk_size`.
The module does not ignore `disk_size`.
The module sets `disk_autoresize = true`.

The `gcp-deploy` and `gcp-destroy` commands do not change.
They do not read the live disk size.

## Reason

The locked Google provider is 8.4.0.
Its `diskSizeCutomizeDiff` function compares the state value with the configured value:

| Change | Auto-resize on | Auto-resize off |
| --- | --- | --- |
| Configured size is larger | Plans an in-place increase | Plans an in-place increase |
| Configured size is smaller | Removes the difference from the plan | Plans a replacement |

Thus, with auto-resize on, Terraform grows a disk to the profile floor.
It never plans a decrease or a replacement.
A disk that auto-resize made larger keeps its size.
A profile scale-down keeps the larger disk.

The module set no `disk_autoresize` value before this change.
The provider default is `true`.
The module now sets the value explicitly, so the protection does not depend on a default.
A contract test locks the value and the growth of an existing disk.

A live disk read in the lifecycle commands is not necessary.
It would add a cloud call, a new failure mode, and duplicate logic that the provider already has.

## Data flow

```text
capacity profile -> render_tfvars -> cloud_sql_disk_size_gb (floor)
Terraform refresh -> live disk size (state)
provider diff: max(state, floor) -> Cloud SQL Admin API update
```

The profile floor stays the only authored value.
No live value goes back into the catalog, the root config, or the deployment bundle.

## Security

The change adds no identity, permission, credential, or network path.
The deploy and destroy identities keep their current roles.
Deletion protection stays on for deploy.

The main risk is data loss from an unwanted instance replacement.
These controls prevent it:

- Auto-resize is on, so the provider removes a decrease from the plan.
- Deletion protection blocks a replacement during deploy.
- The contract test fails if a change removes auto-resize.
- The contract test fails if an existing instance does not grow to a larger floor.

## Residual risk

Auto-resize can grow the disk after Terraform refresh and before the API update.
The update can then send a size that is smaller than the live size.
This design does not remove that race; the window is between refresh and update.

A future provider version can change the diff logic.
Review this design when the provider lock changes the major version.

## Sources

- [google_sql_database_instance](https://registry.terraform.io/providers/hashicorp/google/8.4.0/docs/resources/sql_database_instance): `disk_size` and `disk_autoresize`.
- [Provider diff logic](https://github.com/hashicorp/terraform-provider-google/blob/v8.4.0/google/services/sql/resource_sql_database_instance.go): `diskSizeCutomizeDiff`.
- [Cloud SQL instance settings](https://docs.cloud.google.com/sql/docs/postgres/instance-settings): automatic storage increase.
- [Cloud SQL best practices](https://docs.cloud.google.com/sql/docs/postgres/best-practices): storage headroom.
