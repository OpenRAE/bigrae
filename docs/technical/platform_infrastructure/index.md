# Platform Infrastructure

BigRAE platform workloads use the shared Helm chart on EKS or GKE.
Terraform owns the supporting cloud infrastructure and workload identity grants.

Use the [deployment compatibility reference](deployment-compatibility.md) to distinguish release support from contributor source paths.
Start a new GCP installation with [Install on Google Cloud](../../getting-started/install-gcp.md).

- [AWS EKS backend bundle](aws-eks-bundle.md)
- [AWS native identity](aws-native-identity.md)
- [GCP native identity](gcp-native-identity.md)
- [GCP range audit telemetry](gcp-range-audit-telemetry.md)

AWS support is planned for an upcoming release. See the operations guides:

- [AWS native identity operations](../../ops/aws-native-identity.md)
- [Portal EKS operations](../../ops/portal-eks-operations.md)

## AWS

| Surface | Source | Responsibility |
| --- | --- | --- |
| Account foundation | `platform/terraform/global/` | IAM, runners and developer workstations |
| Core | `platform/terraform/environments/<env>/` | Registries, budgets and shared state services |
| Range | `platform/terraform/environments/<env>/range/` | Range networking and exported provider settings |
| Portal data plane | `platform/terraform/environments/<env>/portal/` | RDS, Redis, Cognito, object storage and secrets |
| Control plane | `platform/terraform/environments/<env>/eks/` | EKS, workload identity and ingress prerequisites |
| Application workloads | `platform/charts/shifter/` | Web, workers, provisioner Jobs, Guacamole and guacd |

The retained `prod` roots are owned by @Brad-Edwards.
Their callers are the bootstrap `terraform`/`full` commands and EKS lifecycle.
Only `aws-dev` is an AWS deployment workflow choice.
Current portal roots contain no CTFd module.
Historical resources require their original source revision and private state for recovery.

Terraform state uses S3 native locking.
Engine/Pulumi state has separate storage and lock ownership.
Unused connector templates and the standalone workshop root are retired.
See [configuration and recovery](../../dev/deployment-configuration.md) before accessing earlier infrastructure revisions.

## GCP

`platform/terraform/gcp/environments/platform/` is the single platform execution root.
Each deployment input bundle supplies its Terraform values.
The current tree contains no committed GCP tenant values directory.
Each deployment keeps its own state bucket/prefix and Terraform metadata directory.
Foundation identity and runner roots remain independent under `gcp/global/`.

| Service | Responsibility |
| --- | --- |
| GKE | Private control plane and platform node pools; Connect Gateway access |
| Cloud SQL | Platform and Guacamole PostgreSQL databases |
| Memorystore | Redis cache and coordination |
| Pub/Sub | Domain events and subscriptions |
| Artifact Registry | Digest-bound control-plane images |
| Secret Manager | Runtime secret bundles and references |
| Cloud DNS / Cloud Armor | Public hostname, TLS and edge policy |

The shared Helm chart owns application workloads.
The deployment renderer supplies values from the bundle, Terraform outputs, and named secret references.
There is no alternative Kustomize deployment path.
Live identities stay in deployment-owned inputs and generated output.

## Related Docs

- [GCP Infrastructure](gcp-infrastructure.md) - GKE, Helm, Cloud Armor, and GCP services
- [GDC Provisioning](gdc-provisioning.md) - Range guest provisioning on GDC
- [Range Instantiation Policy](range-instantiation-policy.md) - Which range backend may serve which kind of launch
- [AMI Management](ami-management.md) - Packer builds and SSM parameter management (AWS)
- [Manual Deployment](manual-deployment.md) - Infrastructure elements deployed without CI/CD
- [CI/CD](cicd.md) - Deployment pipelines
- [GitHub Runners](github-runners.md) - Self-hosted runner setup and maintenance
- [Networking](networking.md) - VPC architecture and peering
- [Guacamole](guacamole.md) - Browser-based RDP integration
