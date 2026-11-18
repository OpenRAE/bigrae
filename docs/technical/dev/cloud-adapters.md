# Cloud Adapters

This reference describes the cloud interfaces and their ownership.
Use the [architecture handbook](../architecture.md) for system context and deployment support limits.
A conforming adapter does not by itself qualify a live backend.

## How It Works

The installation registry defines supported backends and their declared capabilities.
The platform composition root validates `CLOUD_PROVIDER` once through `config._cloud.resolve_cloud_provider`.
Factories consume the validated Django setting and check the required capability before constructing an adapter.
They do not independently choose an AWS fallback.
An unsupported capability raises `CloudProviderNotImplementedError`.

The provisioner resolves its backend through its own configuration root and the same installation registry.
It has no Django dependency.
Keep platform and provisioner protocols separate because their process responsibilities differ.

## Platform Adapters

Source: `shifter/shifter_platform/shared/cloud/types.py`.
Factories: `shifter/shifter_platform/shared/cloud/__init__.py`.

| Protocol | Methods | AWS | GCP |
| --- | --- | --- | --- |
| `ObjectStorage` | `upload_file`, `delete_object`, `copy_object`, `copy_object_conditional`, `object_exists`, `head_object`, `read_object_header`, `download_object`, `generate_presigned_upload_url`, `generate_presigned_download_url`, `tag_object` | S3 | GCS |
| `TaskRunner` | `run_task`, `get_task_status`, `delete_completed_task`, `interrupt_task` | EKS Kubernetes Job | GKE Kubernetes Job |
| `QueueConsumer` | `receive_messages`, `delete_message` | SQS | Pub/Sub |
| `QueuePublisher` | `send_message` | SQS | Pub/Sub |
| `SecretsStore` | `get_secret`, `create_owned_secret`, `retire_owned_secret` | Secrets Manager | Secret Manager |
| `EventBus` | `publish` | SNS | Pub/Sub |
| `CapacityInventory` | `observe` | AWS capacity observations | GCP capacity observations |

Factories include `get_object_storage`, `get_task_runner`, `get_queue_consumer`, `get_queue_publisher`, and `get_secrets_store`.
`get_event_bus` and `get_capacity_inventory` expose the additional platform protocols.
GCE preparation also has the tenant-bound `get_preparation_task` and `get_preparation_readback` factories.

Storage preconditions bind reads and conditional copies to the observed object identity.
Bounded downloads reject oversized or replaced objects.
Task interruption reports control disposition; it does not report range-lifecycle success.
Capacity observation is read-only and reports unavailable observations with a reason code.
Use the source protocol signatures for exact arguments and failure contracts.

## Provisioner Adapters

Source: `shifter/engine/provisioner/cloud/types.py`.
Factories: `shifter/engine/provisioner/cloud/__init__.py`.

| Protocol | Methods | AWS | GCP |
| --- | --- | --- | --- |
| `EventBus` | `publish` | SNS | Pub/Sub |
| `ConfigStore` | `get_parameter` | SSM Parameter Store | Secret Manager |
| `DBAuth` | `generate_auth_token` | RDS IAM authentication | Cloud SQL IAM authentication |
| `SecretsStore` | `get_secret` | Secrets Manager | Secret Manager |
| `ObjectStorage` | `generate_presigned_download_url`, `object_exists`, `upload_new_object`, `delete_object`, `head_object`, `download_object` | S3 | GCS |
| `NetworkInventory` | `list_subnet_cidrs`, `publish_subnet_exhaustion_alarm` | EC2 VPC API | GCE Compute or GDC Kubernetes API |

Factories are `get_event_bus`, `get_config_store`, `get_db_auth`, `get_secrets_store`, `get_object_storage`, and `get_network_inventory`.
An explicit object version binds a signed download URL to that immutable version.
`upload_new_object` refuses replacement of an existing object.
The protocol defines bounded download and identity-precondition failures.

## Adding a New Provider

This how-to section describes the code boundary, not permission to add a backend.
Use the authorized design and current installation contracts first.

1. Register the backend and its actual capabilities in the installation registry.
2. Implement the required protocols in the owning platform or provisioner provider module.
3. Add explicit factory branches for those declared capabilities.
4. Keep cloud-specific conditions inside the adapter and composition boundaries.
5. Add behavioral tests for capability refusal, configuration failure, and the provider's external boundary.
6. Run targeted tests, import checks, and ADR checks for the changed paths.

Do not make business code select behavior by cloud, pack name, or private scenario identity.
Do not report deployment qualification from protocol conformance alone.

## File Locations

| Owner | Location |
| --- | --- |
| Platform protocols and factories | `shifter/shifter_platform/shared/cloud/` |
| Platform implementations | `shared/cloud/aws/`, `shared/cloud/gcp/` within the platform package |
| Provisioner protocols and factories | `shifter/engine/provisioner/cloud/` |
| Provisioner implementations | `cloud/aws/`, `cloud/gcp/` within the provisioner package |
| Backend registry and capability contract | The `installation.registry` and `installation.contract` modules under `shifter/installation/` |

The [API conventions](api.md) and [installation configuration](installation-config.md) describe adjacent interfaces.
