# GCP Infrastructure

This reference describes GCP infrastructure and its source owners.
For installation, use [Install on Google Cloud](../../getting-started/install-gcp.md).
Check [deployment compatibility](deployment-compatibility.md) before selecting a release.

## Directory Structure

```
platform/
├── terraform/gcp/
│   ├── modules/platform-core/       # All GCP platform infrastructure
│   ├── environments/platform/       # Shared platform root for every deployment
│   └── global/                      # cicd-oidc and github-runner roots
├── charts/shifter/                  # Helm chart: the only GCP Kubernetes renderer
└── deployer/gcp/                    # Deployer image of one published release
```

Terraform provisions the GCP resources. The Helm chart packages the BigRAE
control plane. The deploy command (`scripts/bootstrap/deploy.py gcp-deploy`)
renders the generated values from the Terraform outputs, the root config, and
the Secret Manager payloads. Then it installs the chart. A deployment that runs
without GitHub keeps its own Terraform values in its deployment input bundle,
not in this repository.

## Terraform Module: platform-core

Single module provisions the entire GCP control plane.

| Resource | Service | Purpose |
|----------|---------|---------|
| **VPC Networks** (×2) | VPC | `platform` (GKE, shared services) and `range` (guest isolation) |
| **GKE Cluster** | GKE | Private nodes, VPC-native, Workload Identity enabled, Binary Authorization enforced via project singleton policy, private control-plane endpoint; operator access through Connect Gateway |
| **Node Pools** | GKE | Separate access, web, worker, provisioner, and other configured workload pools |
| **Cloud SQL** | Cloud SQL | PostgreSQL. Hosts platform DB and Guacamole DB. Private IP only. |
| **Memorystore** | Memorystore | Redis. Channel layer and worker coordination. |
| **Pub/Sub** | Pub/Sub | Event topic with per-domain subscriptions (cms, engine, mc). |
| **Artifact Registry** | Artifact Registry | Container repositories (portal, guacd, guacamole-client, pulumi-provisioner). |
| **Secret Manager** | Secret Manager | Runtime secret bundles (app, db, guacamole-db, guacamole-json-auth, and separate policy bundles). |
| **Cloud DNS** | Cloud DNS | Optional. Public hostname with Google-managed TLS certificate. |
| **Cloud Armor** | Cloud Armor | Baseline WAF policy attached to the public portal and Guacamole GKE backends. |
| **GCS Buckets** | Cloud Storage | Assets/artifacts and Terraform state. Each Terraform-owned bucket uses its own customer-managed Cloud KMS key ([Bucket encryption keys](../handbook/gcp-github-less-deployment.md#bucket-encryption-keys)). |
| **Service Accounts** | IAM | Separate accounts for GKE nodes and workloads (portal, workers, provisioner). Workload Identity binds K8s SAs to GCP SAs. |

## GKE Cluster

Private nodes with no public node IPs. Cloud NAT provides outbound connectivity.

- **Release channel**: REGULAR (automatic patching)
- **Workload Identity**: Enabled. Pod service accounts map to GCP service accounts.
- **Networking**: VPC-native with secondary IP ranges for pods and services
- **Logging/Monitoring**: System components and workload logging enabled
- **Control-plane access**: private endpoint reached through Connect Gateway;
  optional direct access accepts connected RFC1918 networks only
- **Binary Authorization**: enabled with `PROJECT_SINGLETON_POLICY_ENFORCE`

### Node Pools

| Pool | Role | Notes |
|------|------|-------|
| `access` | Portal and guacd | Exclusive placement and dedicated access pod range |
| `web` | Other web-facing platform workloads | Separate from the access pool |
| `workers` | CMS, Engine, MC background workers | Queue consumers |
| `provisioner` | Range provisioning jobs | Runs K8s Jobs for range lifecycle |
| `runtime_plugins` | Isolated executable adapters | Dedicated plugin pool |

Machine types and node counts are configurable per environment.

## Kubernetes Workloads

Managed via Helm with the chart defaults, the profile values, and the values that `gcp-deploy` generates.

### Chart Resources (`platform/charts/shifter/templates/`)

| Manifest | Workload |
|----------|----------|
| `web-deployment.yaml` | Portal Django app |
| `guacd-deployment.yaml` | Guacamole protocol daemon |
| `guacamole-client-deployment.yaml` | Guacamole web client |
| `worker-cms-deployment.yaml` | CMS queue consumer |
| `worker-engine-deployment.yaml` | Engine queue consumer |
| `worker-mc-deployment.yaml` | Mission Control queue consumer |
| `ctf-scheduler-deployment.yaml` | CTF batch scheduler |
| `rbac-job-launcher.yaml` | RBAC for provisioner K8s Jobs |
| `serviceaccounts.yaml` | K8s service accounts (portal, workers, provisioner) |
| `portal-backendconfig.yaml` | Portal health check + Cloud Armor attachment |
| `guacamole-backendconfig.yaml` | Guacamole Cloud Armor attachment |
| `ingress.yaml` | Public ingress, managed certificate, HTTPS redirect |

### Values files

- `platform/charts/shifter/values.yaml` - chart defaults
- `platform/charts/shifter/values-gcp-dev.yaml` - `gcp-dev` overrides
- `platform/charts/shifter/values-gcp-prod.yaml` - `gcp-prod` overrides
- values that `gcp-deploy` generates - live Terraform outputs, runtime env, exact image identities, and edge policy names. Secret values are not in the Helm values.

## Networking

Dual-network design, same pattern as AWS (see [Networking](networking.md)).

| Network | Purpose |
|---------|---------|
| `platform` | GKE cluster, Cloud SQL (Private Services Access), Memorystore |
| `range` | Guest subnets for range instances. Cloud Router + NAT for egress. |

Networks are peered bidirectionally for platform-to-range connectivity.

Live-fire ranges use GCE range cells (per-range subnets with tag firewall isolation and explicit NAT enrollment) as the approved containment boundary per ADR-030 and ADR-039, with the containment model in ADR-056. Shared-VPC ranges use a provisioner-owned regional Router/NAT with only admitted subnets listed; VPC-per-range cells retain a range-owned Router/NAT. See the [range-cell deploy runbook](../../dev/gcp-range-cell-deploy.md#shared-vpc-nat-capacity-and-event-egress) for capacity and lifecycle bounds. GDC custom L2 networks (VXLAN-based) for per-range guest isolation are a dev and operator-validation path only, not a live-fire containment boundary.

## Deployment Path

One command stands up and updates a GCP deployment:
`scripts/bootstrap/deploy.py gcp-deploy` (ADR-070). `gcp-install` orchestrates initial setup, including the first `gcp-deploy`.
Updates use `gcp-deploy` and the same Helm renderer. An operator runs the
deployer image of a published release
([Install on Google Cloud](../../getting-started/install-gcp.md)). The
[handbook](../handbook/gcp-github-less-deployment.md#what-the-deploy-does)
lists the deploy stages. The retained GitHub CI adapter runs the same command
([Retained GCP CI deploy adapter](../../dev/gcp-ci-adapter.md)).

The deploy command expects and enforces:

- a managed-TLS public hostname from `deployment.domain`
- a private GKE control-plane endpoint that it reaches through Connect Gateway
- Cloud Armor on the public ingress backends
- Terraform-managed Identity Platform for corporate login, with browser-side Google auth and server-side verified-token exchange
- a first operator account that it seeds from `settings.operator_bootstrap`
- the ADR-037 release gates: the exact-digest scan, the provenance check, and the running-image check

`gdc-bootstrap` builds only the legacy GDC VM Runtime substrate for the `gdc`
range backend. It does not deploy the control plane.

## Email delivery

GCP has no native Amazon SES equivalent, so a GCP deployment sends transactional mail (sign-up verification, password reset, invitations) through an operator-chosen SaaS, SendGrid or Mailgun, using `django-anymail`. The AWS deployment is unaffected: it keeps using `django-ses` over its IAM role.

Email is optional. With `email_backend` unset (the default), the portal uses Django's console backend and no email secret is created. To enable it:

1. Set the email variables in the Terraform values of the deployment (`terraform.tfvars` or `terraform.tfvars.json` in the deployment input bundle):

   ```hcl
   # SendGrid
   email_backend      = "anymail.backends.sendgrid.EmailBackend"
   email_from_address = "noreply@your-domain.example"

   # or Mailgun (also needs the sender domain)
   email_backend       = "anymail.backends.mailgun.EmailBackend"
   email_from_address  = "noreply@your-domain.example"
   email_sender_domain = "mg.your-domain.example"
   ```

2. Apply Terraform. This creates an **unseeded** Secret Manager secret `${project_prefix}-email` for the ESP API key. The key is never stored in Terraform state, tfvars, Helm values, or this repo.

3. Read the API key with a silent prompt. Populate the secret as a JSON bundle without putting the key in shell history:

   ```bash
   read -rs -p "ESP API key: " ESP_API_KEY && echo
   printf '{"api_key":"%s"}' "$ESP_API_KEY" \
     | gcloud secrets versions add "${PROJECT_PREFIX}-email" --data-file=- --project "$PROJECT_ID"
   unset ESP_API_KEY
   ```

4. Redeploy. The runtime renderer emits `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, the secret reference `EMAIL_API_KEY_SECRET_ID`, and (for Mailgun) `MAILGUN_SENDER_DOMAIN`; `entrypoint.sh` hydrates the key into `EMAIL_API_KEY` at startup, and `config/_email.py` selects the backend.

If `email_backend` is set without `email_from_address` (or without `email_sender_domain` for Mailgun), the renderer fails closed at deploy time rather than sending as `webmaster@localhost`. See `platform/terraform/gcp/README.md` for the operator runbook.

## Related Docs

- [Cloud Adapters](../dev/cloud-adapters.md) - Protocol-based cloud abstraction
- [Networking](networking.md) - VPC/network architecture (AWS section)
- [Secrets](../dev/secrets.md) - Secret management across clouds
- [CI/CD](../dev/ci-cd.md) - Full CI/CD documentation including GCP workflows
- [Retained GCP CI deploy adapter](../../dev/gcp-ci-adapter.md) - GitHub CI inputs for GCP
- [Terraform](../dev/terraform.md) - Terraform conventions and GCP module patterns
