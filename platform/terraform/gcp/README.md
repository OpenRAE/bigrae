# GCP Terraform

This reference describes the GCP Terraform roots and their ownership.
For installation, use [Install on Google Cloud](../../../docs/getting-started/install-gcp.md).
Use the [compatibility reference](../../../docs/technical/platform_infrastructure/deployment-compatibility.md) before selecting a release.

## Roots

| Root | Purpose |
| --- | --- |
| `environments/platform` | Shared platform root of every GCP deployment. `scripts/bootstrap/deploy.py gcp-deploy` and `gcp-destroy` run it with the state prefix `shifter/<environment>/platform-core`. It creates no image-build resources; guest images are built in a developer build project (#2668). |
| `environments/<deployment>` | Committed Terraform values of the deployments that GitHub CI deploys. A deployment without GitHub keeps its values in its deployment input bundle. |
| `global/cicd-oidc` | Purpose identities that outlive the platform. GitHub federation is optional: an empty `purpose_contexts` creates no pool or provider. `impersonation_principals` names the principals that may impersonate the deploy, release-scan, and destroy identities. `deployment_config_bucket_name` creates the deployment config bucket. |
| `global/github-runner` | Self-hosted runner of a deployment that GitHub CI deploys. |

`scripts/bootstrap/deploy.py gcp-foundation` applies `global/cicd-oidc`. See
the [GitHub-less GCP deployment guide](../../../docs/technical/handbook/gcp-github-less-deployment.md)
for the order of the roots without GitHub.

Current scope:

- project service enablement
- VPC-native GKE foundation
- dedicated peered range VPC for provisioner-owned Compute Engine range subnets
- Cloud SQL PostgreSQL control-plane database over private IP
- shared Cloud SQL databases for the portal and Guacamole client
- Memorystore Redis for channel-layer and worker coordination
- GKE-oriented runtime contract for ephemeral Jobs
- Artifact Registry repositories for core images
- shared GCS bucket for uploads and agent artifacts
- shared Pub/Sub event topic plus worker subscriptions
- reserved global static IP for the public GKE ingress path
- Cloud Armor security policy for the public ingress backends
- optional Cloud DNS managed zone and ingress A record for a configured hostname
- Secret Manager runtime bundles, with seeded portal DB/app and Guacamole DB/JSON-auth secrets
- Identity Platform corporate auth with FirebaseUI/browser-side Google auth flows, allowlisted self-signup, required email verification, required TOTP MFA before app-session creation, and bootstrap-owned first-operator seeding
- reserved private service networking range
- workload and node service accounts with least-privilege runtime roles
- GCS-backed Terraform state bootstrap by the deploy command

Security posture:

- GKE nodes are private-only.
- The GKE control-plane endpoint is private. The deploy command reaches it
  through the IAM-authenticated fleet Connect Gateway, from an operator
  workstation, the deployer image, or CI. Optional authorized networks are
  limited to connected RFC1918 ranges.
- GKE Binary Authorization is enabled (`PROJECT_SINGLETON_POLICY_ENFORCE`) so cluster admission enforces the project's Binary Authorization policy.
- The public application edge is protected with a baseline Cloud Armor policy.
- The GDC workstation and cluster hosts are expected to be private-only and accessed through IAP by bootstrap.
- Platform and range VPCs carry explicit `google_compute_firewall` policy (ADR-008-R4): range ingress denies by default. Its allow rule uses `local.portal_network_cidrs` and `var.range_provisioner_ports`. Platform rules block world-open SSH/RDP and admit Google load-balancer health checks to GKE nodes. Operator break-glass SSH is gated on `var.operator_admin_cidrs` (empty in dev).
- Cloud SQL deletion protection is on by default (`var.cloud_sql_deletion_protection`, default `true`); the platform control-plane database cannot be destroyed without an explicit, environment-root override.
- Memorystore Redis runs on the STANDARD_HA tier with `auth_enabled = true` and `transit_encryption_mode = "SERVER_AUTHENTICATION"` (ADR-008-R6). The runtime entrypoint hydrates the Redis AUTH token from its Secret Manager bundle. It never enters the runtime ConfigMap, generated environment output, or process arguments. Django Channels reads `REDIS_TLS` / `REDIS_PASSWORD` and uses a `rediss://` channels_redis URL host; the helper fails closed if TLS is enabled without a hydrated password.
- Each Terraform-owned GCS bucket uses a customer-managed key from `modules/gcs-cmek` (ADR-008-R5): one key ring per owner/location and one 90-day rotating key per bucket role. The Storage service agent receives its grant before the bucket uses the key. `gcp-deploy` and `gcp-foundation` rewrite the live objects that do not use the key. See the [GCS CMEK design](../../../docs/architecture/gcp-gcs-cmek-design-2564.md). The Terraform state bucket keeps Google-managed encryption, because bootstrap creates it before Terraform runs.
- `gcp-deploy` sets `public_hostname` from `deployment.domain` and sets
  `enable_managed_tls = true`. Before Terraform apply, it reads
  `gke_master_authorized_cidrs` from the Terraform values of the deployment.
  The value must be `[]` for Connect Gateway access, or hold only RFC1918
  CIDRs reachable through connected private networks. Otherwise, `gcp-deploy`
  fails. See
  [`docs/dev/deploy-secrets.md`](../../../docs/dev/deploy-secrets.md) for the
  inputs of a CI-deployed environment.

## Deployment-scoped range-secret project

Set `settings.dynamic_secret_project_id` explicitly in `bigrae.yaml`.
The supported single-project topology sets it equal to `project_id`.
An operator can instead select a separate pre-existing project for range credentials.
The field does not create a project.

The parser validates this value and `bigrae-config render` projects it to Terraform.
Terraform publishes `GCP_DYNAMIC_SECRET_PROJECT_ID` for dynamic writers.
The following separation and migration instructions apply when a separate project is selected.
Keep that dedicated project free of platform bundles, state, application data, and other deployments' secrets.
The cloud/bootstrap owner creates and retires it.
Application Terraform owns Secret Manager enablement, workload IAM, and DATA_READ audit configuration.

The deploy identity needs API enablement, custom-role management, project IAM membership, and Secret Manager audit-configuration authority in the selected project. Runtime authority is narrower:

- provisioner: unconditioned `secretmanager.secrets.create` on the dedicated
  project parent, because Google authorizes create before the secret exists;
- provisioner: the exact get/update/delete/version/IAM-policy verbs, conditioned
  on the deployment's canonical `shifter-<environment>-dynamic-` prefix and the
  Secret resource type;
- portal: read-only access conditioned on the narrower canonical
  `...-dynamic-participant-` prefix;
- range hosts: accessor only on their individual secret.

The create-only parent grant can create arbitrary empty Secret containers in the selected project. It cannot add/read versions, change IAM, or delete out-of-prefix resources. With a separate dynamic-secret project, it cannot create in the platform project. Monitor Secret Manager resource and quota use. Only the bootstrap/operator cleanup identity may remove abandoned out-of-prefix containers. Do not grant provisioner list or broad cleanup authority.

Creation reconciliation rejects exact legacy or canonical read-location containers without a first version after the bounded concurrency wait. It never skips an empty legacy container to create a competing credential or VPN profile. It never publishes a second value beside an active creator.

Retry first. For a persistently empty container, prove the creator has stopped using audit and Job evidence. The bootstrap/operator cleanup identity may then delete that exact container.

Retry the range operation afterward.

Canonical naming also requires an explicit `ENVIRONMENT` value in the runtime
and rejects values outside the lowercase, single-hyphen deployment grammar.
There is no implicit `dev` namespace: missing or malformed configuration fails
before creating a container.

Operator-created inputs are separate. Declare supported GDC references
once in `settings.provisioner_static_secret_refs` as full, versionless
`projects/<project>/secrets/<id>` names. The rendered Terraform map deduplicates
those names for exact per-secret provisioner IAM, and the Terraform output feeds
the same keyed references into runtime env. A missing external secret fails the
apply; there is no project-wide fallback.

### Expand, cut over, drain, contract

1. **Expand:** deploy this code with `dynamic_secret_project_id` explicitly set
   equal to `project_id`. Writers retain legacy names and old ranges are
   unaffected. Populate `provisioner_static_secret_refs` before removing the old
   broad provisioner grant.
2. **Cut over:** pre-create the dedicated project, grant the deploy identity the
   control-plane permissions above, change only `dynamic_secret_project_id`, and
   apply. New secrets use canonical names in the dedicated project. Existing legacy references remain readable and deletable. An unavailable new project fails closed; creation never falls back to the platform project.
3. **Verify:** create and destroy a disposable range, then verify participant access. Run `scripts/gcp/probe_range_secret_permissions.py` with actual provisioner, portal, range-host pool, worker, launcher, and node identities.
   The script is plan-only unless
   `--execute` is supplied and cleans its probe secrets with the operator
   identity.
4. **Drain:** destroy or naturally retire every range generation whose persisted
   reference points at the platform project. Vertex key deletion and VPN/guest
   teardown check both exact locations, so revocation remains generation-bound.
   Do not copy payloads or rotate a live range merely to rename its reference.
5. **Contract:** after the legacy inventory is empty, remove the migration-only
   legacy IAM resources and lookup paths in a contract release. Retire the old project only after independent inventory and audit-log confirmation. Terraform destroy deletes neither project nor live dynamic secrets.

Preview the probe matrix first. Add `--execute` only with approved service-account impersonation and probe-secret creation/deletion authority in the dynamic, platform, and unrelated control projects:

```bash
python3 scripts/gcp/probe_range_secret_permissions.py \
  --platform-project PLATFORM_PROJECT \
  --dynamic-project RANGE_SECRET_PROJECT \
  --unrelated-project UNRELATED_CONTROL_PROJECT \
  --environment ENVIRONMENT \
  --provisioner-service-account PROVISIONER_GSA \
  --portal-service-account PORTAL_GSA \
  --range-host-service-account ASSIGNED_RANGE_HOST_GSA \
  --peer-range-host-service-account PEER_RANGE_HOST_GSA \
  --workers-service-account WORKERS_GSA \
  --launcher-service-account PROVISIONER_LAUNCHER_GSA \
  --node-service-account GKE_NODE_GSA
```

The probe suppresses provider stderr and payload output. It records a run
correlation ID, principal, permission, resource class, fingerprinted resource,
result, and elapsed propagation time. It verifies allowed canonical lifecycle and participant reads.

It checks denied platform-project creation and unrelated-resource lifecycle in separate-project mode. It also checks portal partition/mutation denial and assigned-host access with peer-host denial. Workers, launchers, and GKE nodes must not read dynamic secrets.

Its `finally` cleanup uses the
operator identity in both projects, so even an unexpectedly allowed negative
create does not leave a probe container.

### Capacity and cost envelope (checked 2026-09-07)

The provider quota and price references were rechecked on 2026-11-09.
The earlier per-version access-limit claim was incorrect; those limits apply to version modifications.
Use actual project quotas and billing rates for approval.

Recalculate this section against the linked Google sources and the deployment's
actual metrics before cut-over. The checked-in default bounds the range-host
identity pool at 24 concurrent slots. A conservative planning
case of 10 one-version dynamic secrets per active range therefore gives 240
active versions. A 24-range wave requires approximately 528 writes: `24 × (10 create + 10 add-version + 2 per-secret IAM writes)`. Under a 600-write/minute quota, 72 requests remain for retries and reconciliation. Do not overlap that wave with a full drain (another 240 deletes);
pace or batch provisioning when the measured shape exceeds this envelope.

Current Secret Manager limits are 90,000 access, 600 other read, and 600 write
requests per minute per project. Global secret-version enable, disable, and destroy operations have soft limits of 1 request/second and 60 requests/minute per version. These are modification limits, not access limits. Global `AddSecretVersion` and `UpdateSecret` operations allow 2 requests/second and 120 requests/minute per secret. The portal caches successful reads for 300 seconds, but project access quotas still apply. See
[Secret Manager quotas](https://cloud.google.com/secret-manager/quotas).

Automatic replication counts as one billing location. Active versions beyond the first six cost $0.06/version-month in the US example. Accesses beyond the first 10,000 cost $0.03 per 10,000. If those free tiers
are otherwise unused, 240 active versions plus 200,000 monthly accesses is
`(240 - 6) × $0.06 + (200,000 - 10,000) / 10,000 × $0.03 = $14.61/month`.
Management operations are currently free. This excludes audit-log storage and
other GCP services; use the [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
page and billing-account currency for rollout approval.

DATA_READ audit logs are disabled by Google by default; this stack enables them. The Cloud Logging US example includes 50 GiB/project/month of non-network log storage. Additional ingestion costs $0.50/GiB.

Retention beyond 30 days costs $0.01/GiB-month. Measure probe traffic and a representative hour of range access. Project monthly volume and set the sink/retention budget.

Do not estimate bytes from request counts alone. See
[Cloud Logging pricing](https://cloud.google.com/products/observability/pricing)
and [Secret Manager audit logging](https://cloud.google.com/secret-manager/docs/audit-logging).

Range guests use attached, keyless, predict-only Workload Identity for Vertex (ADR-064). No per-range service-account keys are created. The ten-key-per-principal limit therefore does not bound concurrency. The identity is
least privilege (`aiplatform.endpoints.predict` plus host telemetry) and is
attached only when the model broker is not the guest path. Enabling a specific
model (for example Claude in Vertex Model Garden) is a one-time provider-console
step.

Deleting a secret blocks fresh reads after IAM propagation. Delivered credentials, cached portal values, downloaded VPN profiles, minted OAuth tokens, and service-account keys have separate revocation windows. The rollout owner must record the observed permission-probe propagation
time, allow five minutes for the portal cache, and revoke the guest material.
A downloaded VPN profile stops working when the portal refuses its session,
within one pool heartbeat (#2480). A separate project consumes organization project quota and needs billing, API, and audit-policy authority. Check those deployment-specific limits before requesting creation.

See also Google's
[IAM resource attributes](https://cloud.google.com/iam/docs/conditions-attribute-reference)
and [Data Access audit configuration](https://cloud.google.com/logging/docs/audit/configure-data-access).

## Email delivery (optional)

GCP has no native Amazon SES equivalent, so a GCP deployment sends transactional
mail (sign-up verification, password reset, invitations) through an operator-chosen
SaaS - SendGrid or Mailgun - using `django-anymail`. Email is optional: with
`email_backend` unset (the default) the portal uses Django's console backend and
no email secret is created.

To enable email:

1. Set the email variables in the Terraform values of the deployment
   (`terraform.tfvars` or `terraform.tfvars.json` in the deployment input
   bundle):

   ```hcl
   # SendGrid
   email_backend      = "anymail.backends.sendgrid.EmailBackend"
   email_from_address = "noreply@your-domain.example"

   # or Mailgun
   email_backend       = "anymail.backends.mailgun.EmailBackend"
   email_from_address  = "noreply@your-domain.example"
   email_sender_domain = "mg.your-domain.example"
   ```

2. `terraform apply`. Terraform creates an **unseeded** Secret Manager secret
   `${project_id-prefix}-email` for the ESP API key. The key is never stored in
   Terraform state, tfvars, Helm values, or this repo.

3. Populate the secret with your ESP API key as a JSON bundle (the runtime
   entrypoint reads the `api_key` field). Read the key from a silent prompt so
   it never lands in shell history, command lines, or process arguments:

   ```bash
   read -rs -p "ESP API key: " ESP_API_KEY && echo
   printf '{"api_key":"%s"}' "$ESP_API_KEY" \
     | gcloud secrets versions add "${PROJECT_PREFIX}-email" --data-file=- --project "$PROJECT_ID"
   unset ESP_API_KEY
   ```

   `printf` is a shell builtin. The value travels through the shell variable and stdin, outside process arguments and shell history. Alternatively,
   write the JSON to a `chmod 600` file and pass it with `--data-file=<path>`.

The deploy renderer (`scripts/gcp/render_runtime_env.py`) emits `EMAIL_BACKEND`,
`DEFAULT_FROM_EMAIL`, the secret **reference** `EMAIL_API_KEY_SECRET_ID`, and (for
Mailgun) `MAILGUN_SENDER_DOMAIN`; the entrypoint hydrates the key into
`EMAIL_API_KEY` at startup. See `shifter/shifter_platform/config/_email.py` for
the backend selection.

Current non-goals:

- guest VM / NGFW / Compute Engine range infrastructure beyond the shared range-network foundation

CI validates this tree with `terraform init -backend=false` and
`terraform validate` on pull requests. A deploy, from CI or from an operator,
creates and hardens the GCS backend bucket `${project_id}-terraform-state` if
needed. Then it applies the shared platform root with the deployment's state
prefix.

The environment outputs now also expose the provider-neutral range-network
contract consumed by the provisioner runtime:

- `range_network_id`
- `range_network_cidr`
- `range_network_region`
- `portal_network_cidrs`

Example concrete values:

- `project_id = "example-gcp-project"`
- `public_hostname = "shifter.example.com"`
- `enable_managed_tls = true`
- `gke_master_authorized_cidrs = []`; operator and CI access use Connect Gateway

Operational note:

- `create_dns_managed_zone = false` is intentional. DNS is assumed to be managed outside this Terraform tree for now. `shifter.example.com` must resolve to the reserved ingress IP before the Google-managed certificate will become active.
