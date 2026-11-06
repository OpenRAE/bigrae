# Technical Documentation

Platform architecture, infrastructure, and development documentation.

For installation, use [Install on Google Cloud](../getting-started/install-gcp.md)
or [Deploy with a coding agent](../getting-started/deploy-with-agent.md).
Both use the published release container. AWS support is coming.

## Architecture

- [BigRAE identifier inventory](../architecture/bigrae-rename-inventory.md)
- [BigRAE rename cutover and rollback](../how-to/bigrae-rename-cutover.md)

- [Current-state architecture handbook](architecture.md) - System, authority, lifecycle and package ownership
- [First sign-in](handbook/gcp-first-run.md) - Sign in to a new deployment and check it
- [GCP deployment reference](handbook/gcp-github-less-deployment.md) - Release, foundation, inputs, deploy, update, teardown, and bucket encryption keys without GitHub
- [Scenario contract transition](handbook/scenario-contract-transition.md) - CyberScript, ACES and current RAES
- [Per-range model-access design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/model-access/index.md) - Proposed architecture, security, operations, ADRs, and implementation backlog for #681
- [Model-access contracts](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/model-access/architecture.md) - Proposed ownership, allocation, accounting, protocol, and lifecycle contracts

## Platform Domains

- [Platform Overview](shifter_platform/index.md) - Domain architecture
- [Mission Control](shifter_platform/mission_control.md) - Presentation layer
- [Engine](shifter_platform/engine.md) - Range orchestration
- [CMS](shifter_platform/cms.md) - Content management
- [Management](shifter_platform/management.md) - Administration

## Infrastructure

- [Infrastructure Overview](platform_infrastructure/index.md) - AWS and GCP components
- [GCP Infrastructure](platform_infrastructure/gcp-infrastructure.md) - GKE, Cloud SQL, Helm, Cloud Armor, and GCP services
- [GCP Event Capacity](platform_infrastructure/gcp-event-capacity.md) - Versioned shared-service profiles, projections, drift, and the p30 gate
- [GDC Provisioning](platform_infrastructure/gdc-provisioning.md) - Range guests on GDC (KubeVirt, pods)
- [Range Instantiation Policy](platform_infrastructure/range-instantiation-policy.md) - Which range backend may serve which kind of launch
- [Networking](platform_infrastructure/networking.md) - Network architecture (both clouds)
- [CI/CD](platform_infrastructure/cicd.md) - Deployment pipelines
- [Machine Images](platform_infrastructure/ami-management.md) - AMIs (AWS) and GDC images
- [Guacamole](platform_infrastructure/guacamole.md) - Terminal infrastructure
- [Manual Deployment](platform_infrastructure/manual-deployment.md) - Manual setup steps

## Development

- [Development Overview](dev/index.md) - Getting started with development
- [Local Setup](dev/local-setup.md) - Local environment
- [Developer environment setup](dev/setup.md) - Deploy a development environment from a fork with GitHub Actions
- [AWS native identity](../ops/aws-native-identity.md) - Identity and policy operations for AWS development deployments
- [Portal on EKS operations](../ops/portal-eks-operations.md) - Operate the portal in AWS development deployments
- [Terraform](dev/terraform.md) - Infrastructure patterns
- [CI/CD](dev/ci-cd.md) - Pipeline configuration
- [Secrets](dev/secrets.md) - Secrets management
- [Platform API Development](dev/api.md) - DRF endpoint, schema, scope, and error-envelope conventions
- [Cloud Adapters](dev/cloud-adapters.md) - Cloud abstraction layer
- [Principles](dev/principles.md) - Engineering philosophy
- [ADR Enforcement](dev/adr-enforcement.md) - Architecture guardrails and policy checks

## Operations reference

- [GCP native identity](../ops/gcp-native-identity.md)
- [GCP range audit telemetry](../ops/gcp-range-audit-telemetry.md)

## Planning & Notes

Internal planning documents and development notes.

- [Plans](plans/) - Implementation plans
- [Notes](notes/) - Development notes
