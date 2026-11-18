# Register GCP range projects

Use this guide to register an existing dedicated GCP project and capture its original managed state.
Registration alone does not qualify a live range or deploy anything.
It does not create a project, enable APIs, or grant cloud roles.
Source verification of the implemented runtime does not establish live qualification.

## Before registration

You need the explicit `installation.manage_cloud_authority` permission.
Staff status alone does not grant it.
The selected project belongs to one organization in BigRAE.
It must be separate from deployment control, shared infrastructure, and credential storage projects.
Use a dedicated project whose managed metadata fits the [technical contract's baseline budget](../technical/shifter_platform/registered-gcp-range-projects.md).

## Register and inspect the project

1. Send an authenticated request to `POST /api/v1/cms/gcp-range-projects/` with only these fields:

   ```json
   {
     "organization_uuid": "00000000-0000-4000-8000-000000000001",
     "project_id": "synthetic-project"
   }
   ```

   A successful request returns HTTP 202.
   A new registration has `status: pending`.
   The portal queues capture for the provisioner worker. It does not access project IAM.
   An identical repeated registration returns the same record, including its current status.
   A repeated request cannot assign the project to another organization.

2. Read `GET /api/v1/cms/gcp-range-projects/` to inspect status.

   Each page contains at most 50 records.
   Pass the returned `next_cursor` as `cursor` to continue.
   An accepted capture sets `status: ready`.
   A failed capture leaves the project unavailable with a bounded failure code.
   Responses contain no baseline inventory, object location, or credentials.

## Disable new allocation

Send `POST /api/v1/cms/gcp-range-projects/<id>/disable/` with an empty object.
Disabling does not erase a running range's custody or retained restoration evidence.
A capture already running cannot re-enable a disabled registration when it finishes.

A project remains held after failure, cancellation, or incomplete teardown.
Only the current accepted destroy result with exact baseline restoration can release it.
Investigate incomplete restoration through the approved tenant operations procedure.
Do not delete lease records to make a project available.

## Retry capture or re-enable registration

Send `POST /api/v1/cms/gcp-range-projects/<id>/retry/` with an empty object.
A failed capture can be retried. A disabled registration can be re-enabled.
A baseline that was never accepted can be captured again.

An accepted original baseline is immutable.
Re-enabling queues independent readback against that baseline and fails on drift.
A project held by a range cannot be re-enabled through this endpoint.
