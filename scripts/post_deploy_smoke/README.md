# Post-deploy range smoke (#218)

Use this how-to guide to check provisioning, connectivity, and request-owned teardown on an authorized test deployment.
The harness creates billable range resources.
Obtain range-operation authority, confirm the target and quota, and keep an incident owner available until cleanup is verified.
This check does not qualify private scenario content.

The smoke validates the **platform** (range provisioning, guest connectivity,
teardown), not scenario content. Each variant provisions a minimal range built
entirely from the base range AMIs. `linux` uses the `smoke_linux` scenario
(Kali attacker + Ubuntu victim, SSH probe) and `windows` uses `smoke_windows`
(Kali attacker + plain Windows victim, RDP probe). Every instance is
`os_type` kali/ubuntu/windows with `xdr_agent: false`, so **no XDR agent is
required**. XDR/agent install is scenario-specific content and is exercised by
real scenarios, not by the post-deploy smoke (#1422).

## Required environment

- `SMOKE_TEST_USER_EMAIL`: dedicated automation identity (for example
  `smoke@example.com`); created in Django on first run if missing.
  No mailbox or interactive login is required by the harness.
  Account creation alone does not grant current native application authority.
  Confirm the selected actor and deployment satisfy the range service authorization contract.
- AWS credentials with SSM access to the portal EC2 instance
- `ENV` (default `dev`) and optional `PORTAL_INSTANCE_TAG` (default `${ENV}-portal`)

For GCP, use an authenticated `kubectl` context for the target platform cluster
instead of AWS credentials. The harness derives a short-lived Job from the live
`portal-web` pod template in `shifter-platform`, retaining its exact image,
service account, access-pool placement and runtime configuration. The Job and
its temporary identity Secret are deleted on exit. This avoids relying on the
streaming `kubectl exec` transport through GKE Connect Gateway.

For current GCP releases, catalog setup follows native activation and application readiness.
The deployment uses the recorded bootstrap administrator or a supplied native credential file.
It registers through ordinary ingestion, conformance, and publication services.
A missing proof leaves catalog setup incomplete with a warning.
See [native identity operations](../../docs/ops/gcp-native-identity.md#live-acceptance-evidence).

## Local usage

```bash
export ENV=dev
export AWS_PROFILE=<dev profile>
export SMOKE_TEST_USER_EMAIL=smoke@example.com
bash scripts/smoke-test.sh --variant linux
bash scripts/smoke-test-windows.sh
```

For GCP, prefer `gcp-smoke` from the verified release deployer image.
A contributor with an approved cluster context can invoke the wrapper directly:

```bash
bash scripts/smoke-test-gcp.sh --variant linux
```

The retained `_gcp-dev.yml` adapter invokes the same smoke after deployment.
No GCP target is selectable in the current `deploy.yml`.
An empty `settings.post_deploy_smoke.user_email` skips release smoke and supplies no range evidence.

Do not substitute a direct provisioner/backend call: accepted evidence must
show the CMS-created `smoke_linux` range reached READY, the SSH probe succeeded,
and request-owned destroy completed. Record the target environment, request ID,
terminal status, probe result, and cleanup result without copying credentials
or guest secret values.

The management command prints `destroy requested` after the product accepts the
request; provider teardown continues asynchronously. For a manual acceptance
run, also wait for the named destroy Job in `shifter-jobs` to reach `Complete`
and verify the request's range-owned resources are absent. Do not delete those
resources directly to make the smoke pass. The wrapper's short-lived Job and
identity Secret in `shifter-platform` must also be absent after it exits.

Implementation lives in `cms/post_deploy_smoke/` and
`python manage.py run_post_deploy_smoke`.
