# Technical Documentation

Use this landing page to find current explanations, technical references, and development tasks.

## Architecture

- [BigRAE identifier inventory](../architecture/bigrae-rename-inventory.md)
- [BigRAE rename cutover and rollback](../how-to/bigrae-rename-cutover.md)

- [Current-state architecture handbook](architecture.md) - System, authority, lifecycle and package ownership
- [Install on Google Cloud](../getting-started/install-gcp.md) - Install a deployment from a published release
- [GitHub-less GCP deployment](handbook/gcp-github-less-deployment.md) - Release, foundation, inputs, deploy, update, teardown, and bucket encryption keys without GitHub
- [Scenario contract transition](handbook/scenario-contract-transition.md) - CyberScript, ACES and current RAES
- [Per-range model-access design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/model-access/index.md) - Historical broker design for #681; #2909 removed the broker (ADR-068)

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
- [Developer environment setup](dev/setup.md) - Deploy a development environment from a fork with GitHub Actions on `aws-dev`
- [AWS native identity](../ops/aws-native-identity.md) - Identity and policy operations for AWS development deployments
- [Portal on EKS operations](../ops/portal-eks-operations.md) - Operate the portal in AWS development deployments
- [Terraform](dev/terraform.md) - Infrastructure patterns
- [CI/CD](dev/ci-cd.md) - Pipeline configuration
- [Secrets](dev/secrets.md) - Secrets management
- [Platform API Development](dev/api.md) - DRF endpoint, schema, scope, and error-envelope conventions
- [Cloud Adapters](dev/cloud-adapters.md) - Cloud abstraction layer
- [Principles](dev/principles.md) - Engineering philosophy
- [ADR Enforcement](dev/adr-enforcement.md) - Architecture guardrails and policy checks

## Planning & Notes

These preserved records retain their own dates and applicability.
They do not replace current operating instructions.

- [Plans](https://github.com/OpenRAE/bigrae/blob/dev/docs/technical/plans/README.md) - Implementation plans
- [Notes](https://github.com/OpenRAE/bigrae/blob/dev/docs/technical/notes/README.md) - Development notes

## Qualification and contribution

- [QA protocols](../qa/index.md): choose a live verification procedure and its authority boundary.
- [Testing reference](../dev/testing.md): exact lane commands, quality owners, coverage, and warning policy.
- [Contribution workflow](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md): prepare source or documentation changes.
- [Release workflow](../DEVELOPMENT_WORKFLOW.md): maintainer promotion and release approvals.
- [Built-image smoke](https://github.com/OpenRAE/bigrae/blob/dev/scripts/stack-smoke/README.md): local fixture architecture and runtime evidence.
- [Guacamole authority extension](https://github.com/OpenRAE/bigrae/blob/dev/shifter/engine/guacamole/authority-extension/README.md): native lease and qualification reference.
- [In-box bootstrap seed](https://github.com/OpenRAE/bigrae/blob/dev/shifter/shifter_platform/cms/scenarios/inbox_packs/README.md): manifest and ingestion ownership.
- [MCP operations security](https://github.com/OpenRAE/bigrae/blob/dev/mcp/ops/SECURITY.md) and [NGFW discovery security](https://github.com/OpenRAE/bigrae/blob/dev/mcp/ngfw/SECURITY.md): exact tool boundaries.
