# AWS EKS backend bundle

The AWS backend packages platform workloads with EKS and `platform/charts/shifter`. The provisioner runs as a Kubernetes Job, as on GCP. Range and target delivery (the
VMs inside a range) remain ECS/VM behind the existing ADR-039 range adapter;
Cognito remains the user identity provider. These are separate boundaries.

## Authoritative inputs and owners

The explicit entrypoint is:

```console
./scripts/bootstrap/deploy.py eks-deploy \
  --config bigrae.yaml \
  --images .shifter/images.json \
  --profile operator
```

`bigrae.yaml` must select `backend: aws`. The image file is a JSON mapping
whose values are attested `repository@sha256:<digest>` identities. Tags are
rejected.

Protected input files must resolve beneath the repository, the system
temporary directory, `RUNNER_TEMP`, or an operator-selected
`SHIFTER_PROTECTED_INPUT_ROOT`; symbolic links are rejected. The lifecycle validates root configuration and runs shared preflight. It applies a saved plan from isolated `platform/terraform/environments/<profile>/eks`.

It obtains cluster access through the Terraform-output deploy role and performs an atomic Helm upgrade.

Terraform owns the cluster, private placement, workload identity roles,
certificate/WAF/DNS prerequisites, KMS, and secret stores. Helm owns namespaced
platform workloads. ECS/ASG portal state and range task state are outside the
EKS root and are never imported, adopted, renamed, or destroyed by it.

The protected EKS JSON var-file supplies a closed `addon_versions` object for
VPC CNI, CoreDNS, kube-proxy, EBS CSI, EFS CSI, and the AWS Secrets Store CSI
provider. Every value is a reviewed `vX.Y.Z-eksbuild.N` release compatible with
the root's pinned Kubernetes version. The EKS module owns the Load Balancer
Controller permission document; deployment inputs must not supply a controller
policy ARN. Before enabling EKS, apply `platform/terraform/global/iam` so the
GitHub deploy role has its environment-scoped EKS/OIDC policy.
The chart renderer gives the sole platform ingress the deterministic
`<cluster>-platform` ALB name. The controller policy uses that exact ARN
namespace for WAF association because WAFv2 does not honor ELB ownership-tag
conditions.

## Security boundaries

- GitHub OIDC authorizes the protected deployment runner.
- EKS workload identity binds exact namespace/service-account subjects to
  workload roles; pods do not inherit node-wide credentials.
- Cognito/OIDC authenticates users and is not cluster authentication.
- Provider values carry public settings and secret references only. Runtime
  values are hydrated from Secrets Manager by the existing entrypoint boundary;
  they do not enter Helm values, ConfigMaps, argv, or committed files.
- The shared chart renders restricted, non-root, read-only workloads with
  bounded resources and default-deny network policy. The Kubernetes Job
  launcher is enabled for AWS: the provisioner runs as an admission-gated Kubernetes Job (ADR-044-R6). Controls include exact-subject launcher/provisioner IRSA, dedicated-launcher RBAC, and restricted Pod Security. Admission fails closed. Range and target delivery remain ECS/VM behind the
  ADR-039 range adapter.
- Every module-created role carries the installation CI permissions boundary.
  Controller roles remain separate: VPC CNI, EBS CSI, EFS CSI, the Load
  Balancer Controller, and cluster-autoscaler each bind their exact
  `kube-system` ServiceAccount. The Secrets Store CSI provider receives no
  controller-wide secret-reader role; a future consumer continues to use its
  own exact-subject workload role.
- VPC CNI enables NetworkPolicy with strict startup enforcement. Public client
  CIDRs restrict the ALB through `alb.ingress.kubernetes.io/inbound-cidrs`;
  pod-side NetworkPolicy separately admits target traffic from the EKS public
  ALB subnets. These are different network hops and are not interchangeable.

## Provisioner environment sourcing (ADR-044-R6)

The provisioner Job's environment is composed over the existing portal and
range data plane rather than owned by the EKS bundle. The range stack publishes
its topology (VPC/subnet/route-table/security-group IDs, endpoint IDs, ARNs) to
`/shifter/<env>/range/*` in SSM Parameter Store, since those opaque IDs are not
discoverable by a native `data.aws_*` lookup. The `eks-provisioner-env` module reads that contract and the `/shifter/ami/*` pointers. Native AWS data sources supply shared portal RDS, secrets KMS, agent bucket, and VPC metadata. The module merges those values with management-plane runtime configuration. `terraform_remote_state` is never used
(enforced by the `eks-cross-stack-sourcing` guard); secret payloads flow only as
references through the existing hydration boundary.

## Bundle metadata and doctor

The AWS entry in the backend bundle registry
(`shifter/installation/registry.py`) is the machine-readable contract that
`bigrae-config doctor` reads to detect missing prerequisites and secret wiring
before a deploy. There is one generic doctor entrypoint; AWS-specific readiness
is declared through the bundle's `required_tools`, `required_secrets`,
`validation_checks`, and `health_checks`, not through provider-specific doctor
code.

The AWS bundle declares the pre-mutation validation front doors, the fast
credential-free checks doctor runs before touching infrastructure:

- `root-config`: validate the `bigrae.yaml` shape with `bigrae-config validate`.
- `terraform-fmt`: `terraform fmt -check -recursive platform/terraform/environments`.
- `helm-template`: render `platform/charts/shifter` with `values-aws-dev.yaml`.
  This checks AWS value shapes before deployment.
- `eks-preflight`: run `scripts/bootstrap/preflight.py --config bigrae.yaml --component eks`. It derives cloud/profile from the root config and checks tools, the isolated EKS root, and backend inputs. Doctor and deployment reuse this shared prerequisite specification.

The shared chart is the Kubernetes surface of both AWS and GCP; neither backend
has a Kustomize overlay (#2571). `helm-template` is therefore the Kubernetes
front door rather than an overlay render or a raw-manifest kube-linter pass. The fuller pre-mutation suite
(tflint with init, Checkov, kube-linter and kubeconform on the rendered chart,
and effective-values schema validation) stays enforced in CI and the deploy
lifecycle.

The bundle's `generated_outputs` enumerate the complete runtime-env key set the
renderer emits into the ConfigMap, derived from
`installation.runtime_inventory_aws.AWS_GENERATED_RUNTIME_ENV_KEYS`. That set
mirrors the Terraform `merged_runtime_env` (the renderer-validated required
bindings, the `eks-provisioner-env` range and portal topology the
`provisioner_env` block re-supplies) plus the renderer-owned keys, so the published contract
and `render_aws_values` cannot drift. An oracle test drives a representative
`render_aws_values` and asserts the emitted keys equal the classified set.

`OIDC_SECRET_ID` is classified as a Secrets Manager reference; `APP_SECRET_ARN`
and `DB_SECRET_ARN` are the compatibility aliases `entrypoint.sh` normalizes;
every other projected key is public runtime configuration. Process roles are
derived per key (portal and worker always, provisioner for the keys the launcher
forwards to the Job). AWS ranges are delivered on ECS/VM rather than Kubernetes
range-task pods, so no AWS output declares the range-task consumer.

Hydrated values such as `DC_DOMAIN_PASSWORD` are excluded. They are not renderer output and must never enter a ConfigMap.

The AWS operator settings model (`AwsSettings`) and secret-reference grammar
live in `installation.settings_aws`, mirroring `installation.settings_gcp`.

## Teardown and evidence

```console
./scripts/bootstrap/deploy.py eks-teardown \
  --config bigrae.yaml \
  --profile operator
```

Teardown removes the Helm release, destroys only the isolated EKS root, and
fails if that Terraform state remains non-empty. Deployment requires all managed add-ons `ACTIVE` and completed controller/chart rollouts. Admission must deny a non-launcher provisioner Job.

Live Deployment and Job probes must confirm default-deny NetworkPolicy. Every workload/controller ServiceAccount must receive its expected caller role and be denied sibling roles. HTTPS `/health/` must succeed.

Diagnostic objects are bounded and removed
unconditionally; projected tokens remain inside pod files and are never logged
or passed in process arguments.

For transition guidance, follow
[Migrate an AWS deployment from ECS to EKS](../../how-to/aws-ecs-to-eks-migration.md).
