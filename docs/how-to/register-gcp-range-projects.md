# Register GCP range projects

The implementation for #2716 registers an existing dedicated GCP project and
captures its original managed state. Cloud IAM and Secret Manager scenario
realization is still under development. Registration alone does not qualify a
live range, deploy anything, create a project, enable APIs or grant cloud roles.

An installation administrator needs the explicit
`installation.manage_cloud_authority` permission. Staff status alone does not
grant it. The selected project belongs to one organization in BigRAE and must
be separate from deployment control, shared infrastructure and credential
storage projects. Use a dedicated project whose managed metadata fits the
baseline budget described in the [technical contract](../technical/shifter_platform/registered-gcp-range-projects.md).

Use the authenticated `POST /api/v1/cms/gcp-range-projects/` endpoint with only
these fields:

```json
{
  "organization_uuid": "00000000-0000-4000-8000-000000000001",
  "project_id": "synthetic-project"
}
```

A successful request returns HTTP 202 and `status: pending`. The portal queues
capture for the provisioner worker; it does not access project IAM. Repeating
an identical registration returns the same record. A project cannot be assigned
to another organization through a repeated request.

Read `GET /api/v1/cms/gcp-range-projects/` to inspect status. Each page contains
at most 50 records; pass the returned `next_cursor` as `cursor` to continue.
A successful accepted capture sets `status: ready`; failed capture leaves the
project unavailable with a bounded failure code. Responses contain no baseline
inventory, object location or credentials.

Use `POST /api/v1/cms/gcp-range-projects/<id>/disable/` with an empty object to
prevent new allocation. Disabling does not erase a running range's custody or
its retained restoration evidence. A capture already running cannot re-enable
a disabled registration when it finishes.

A project remains held after failure, cancellation or an incomplete teardown.
Only the current accepted destroy result with exact baseline restoration can
release it. Investigate incomplete restoration through the approved tenant
operations procedure; do not delete lease records to make a project available.

Use `POST /api/v1/cms/gcp-range-projects/<id>/retry/` with an empty object
to retry failed capture or re-enable a disabled registration. A never-accepted
baseline can be captured again. Once accepted, the original baseline is immutable:
re-enable queues independent readback against it and fails on drift. A project
held by a range cannot be re-enabled through this endpoint.
