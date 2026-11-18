# Machine Image Management

## AWS (AMIs)

AMI IDs stored in SSM Parameter Store, built via Packer workflows.

## SSM Parameters

| Parameter | Purpose |
|-----------|---------|
| `/shifter/ami/kali` | Kali attacker instance |
| `/shifter/ami/ubuntu` | Ubuntu victim instance |
| `/shifter/ami/windows` | Windows victim instance |
| `/shifter/ami/dc` | Domain Controller instance |

The build workflow publishes each type to `/shifter/ami/<type>`; the provisioner resolves both the legacy known types and any custom key from that path.

Provisioner fetches AMI IDs at runtime via `shifter/engine/provisioner/provisioner_ami.py:get_ami_id()`.

## AMI Types

### Packer-Built AMIs

The kali, ubuntu, and windows AMIs are built from base images using Packer (the `build` job in `packer.yml`).

| AMI | Base Image | Build Scripts |
|-----|------------|---------------|
| **kali** | Official Kali AMI | `shifter/packer/scripts/kali/` |
| **ubuntu** | Ubuntu 22.04 | `shifter/packer/scripts/ubuntu/` |
| **windows** | Windows Server 2022 | `shifter/packer/scripts/windows/` |

Build configuration: `shifter/packer/*.pkr.hcl` (one file per type).

### External image recipes

Pack-specific images and their build pipelines belong to pack authors. Register
immutable image artifacts through the supported preparation contract; core image
workflows build only platform base images.

### Prebaked DC AMI

Domain Controller uses a manually created AMI with AD DS already promoted.

| Property | Value |
|----------|-------|
| Domain | `internal.shifter` |
| NetBIOS | `INTSHIFTER` |
| Hostname | Fixed from AMI (typically `DC01`) |
| AMI IDs | `shifter/packer/dc-amis.json` |

**Critical:** The prebaked DC's Administrator password must match the
environment's domain password in AWS Secrets Manager (`shifter-{env}-portal-dc-domain`).
The portal Terraform root generates and seeds `random_password.dc_domain_password`. The AMI build reads that managed value from Secrets Manager instead of selecting another password. Victims use the same password
for domain join. The value must never be committed to `terraform.tfvars`,
workflow YAML, or any other tracked file.

DC AMI is prebaked because runtime promotion adds 15-20 minutes to provisioning. Tradeoffs:
- Fixed domain name across all ranges
- Fixed hostname (no per-range DC naming)
- Password rotation must be coordinated between the AMI and the runtime secret

## Workflows

### Build (Dev)

Workflow: `.github/workflows/packer.yml`

| AMI Type | Action |
|----------|--------|
| kali, ubuntu, windows | Packer build, fresh-boot SSM/DNS validation gate, then update dev SSM |
| dc | Read the id from `dc-amis.json` (trusted `dev` provenance, validated), update dev SSM |

The `kali`, `ubuntu`, and `windows` builds bake a deterministic AmazonProvidedDNS
upstream into the guest (issue #1633) so DNS is race-free from first boot. Before changing `/shifter/ami/<type>`, the validation gate boots the exact candidate in a range-equivalent subnet. It requires SSM registration and regional SSM DNS resolution on fresh boot and after reboot.

A
failed candidate leaves the previous known-good id in place. The gate reads subnet, security group, and instance profile from trusted `PACKER_VERIFY_*_<ENV>` repository variables. Dispatch inputs do not select them.

See the [AMI seeding runbook](../../dev/aws-ami-seeding-runbook.md).

The base `build` job assumes a dedicated least-privilege image-pipeline IAM role
(`github_actions_image` in `platform/terraform/global/iam`, issue #1656), not the
broad deploy role. OIDC trust permits exact protected `dev`/`main` subjects. `iam:PassRole` permits only the `shifter-<env>-range-range-instance` EC2 role. The verification instance cannot receive another role. The role ARN is wired to the
`AWS_IMAGE_ROLE_ARN_<ENV>` secret (see the runbook cutover); the
`check_tf_iam_role_naming` guardrail (ADR-004-R22) pins the exact-subject and
exact-range-role invariants. `bake-scenario` keeps its own separate role.

### Promote (Prod)

Workflow: `.github/workflows/packer-promote.yml`

| AMI Type | Action |
|----------|--------|
| kali, ubuntu, windows | Copy AMI to prod account, update prod SSM |
| dc | Read the id from `dc-amis.json` (trusted `dev` provenance, validated), update prod SSM |

`packer-promote.yml` handles only kali, ubuntu, windows, and dc.

Both DC publishers read `dc-amis.json` from a dedicated protected-`dev` checkout. They never use the dispatched ref, build ref, or runner leftovers. The shared `shifter/packer/scripts/bake/resolve-dc-ami.sh` validator checks presence and AMI syntax. EC2 must report the image `available` and owned by the target account. The prod
promote job also runs only from a protected ref (`dev`/`main`). See issue #1656.

## Updating AMIs


1. Modify scripts in `shifter/packer/scripts/`
2. Run "Packer AMI Build" workflow for the type
3. Test in dev
4. For promotable types (kali, ubuntu, windows), run "Packer AMI Promote to Prod"

### Domain Controller

1. Edit `shifter/packer/dc-amis.json` with new AMI ID
2. Run "Packer AMI Build (Dev)" workflow with `dc` type
3. Test in dev
4. Run "Packer AMI Promote to Prod" workflow with `dc` type

To create a new DC AMI:

1. Launch Windows Server 2022 base AMI
2. Install AD DS feature
3. Promote to DC with domain `internal.shifter`, NetBIOS `INTSHIFTER`
4. Set the domain Administrator password to the value already seeded in
   `shifter-{env}-portal-dc-domain` (Terraform-managed; read it from Secrets
   Manager, do not invent one), see `dev/secrets.md`
5. Set DC DNS forwarders to link-local AmazonProvidedDNS. This makes external names, including the regional SSM endpoint, resolve deterministically (issue #1633): `Set-DnsServerForwarder -IPAddress 169.254.169.253 -PassThru`. This is
   the DC-role equivalent of the `FallbackDNS` baked into the Linux guests. Do
   not reset the DC's adapter to DHCP DNS: a promoted DC points its client at
   itself and forwards outbound queries, so a DHCP reset would break domain
   resolution.
6. Sysprep and create AMI
7. Update `dc-amis.json`

**Important:** The Administrator password set during promotion must match the
runtime secret referenced by the portal/engine Terraform stack for domain join
to work. Keep only non-secret identifiers in Terraform configuration; do not
store the password value in environment tfvars.

## Related Files (AWS)

| File | Purpose |
|------|---------|
| `shifter/packer/dc-amis.json` | DC AMI IDs (version controlled) |
| `shifter/engine/provisioner/provisioner_ami.py` | `get_ami_id()` function |
| `shifter/engine/provisioner/catalog/instances.py` | Instance type definitions |
| `shifter/engine/provisioner/plans/dc_setup.py` | DC verification (no promotion step) |

## GCP

GCP keeps four distinct image concepts separate (do not conflate them with AWS
AMIs):

### GCE guest images (Packer)

Compute Engine guest images are built with Packer, parallel to the AWS AMI flow
(issue #505, PLAT-001.10). They are **not** AMIs and their refs are **never**
stored in AWS SSM `/shifter/ami/*`.

- Templates: `shifter/packer/gcp/*.pkr.hcl` (`googlecompute` builders), a
  separate Packer configuration from the AWS `amazon-ebs` templates one
  directory up—`packer` invoked in either directory never sees the other.
- **Version pointer = the release manifest.** Each build creates image
  `shifter-<type>-<timestamp>` in the developer build project. Each release
  names the newest verified publication of each role, and the deploy imports
  those images into the range project (the GCP analog of the AWS SSM
  parameter).
- Build: `.github/workflows/packer-gcp.yml` (`workflow_dispatch`,
  `ubuntu-latest` + purpose-scoped Workload Identity Federation into the
  developer build project). It calls `.github/workflows/packer-gcp-validate.yml`
  for the exact candidate. Only after validation passes, it publishes the image
  to the release registry with signed build provenance (#2668). No promotion
  step exists.
- Image types: `ubuntu`, `kali`, `dc-prebaked` (published as `dc`). **Kali** uses a GCE-native `debian-12` base converted to Kali Rolling by the first provisioning script. The official genericcloud disk lacks required GCE guest integration. See `shifter/packer/gcp/README.md`.
- Agent trigger: the `build_gce_image` MCP ops tool (`infra_mutation`),
  parallel to `build_ami`.

> Guest specialization that is AWS-specific in the shared provisioning scripts
> (the SSM agent; Claude Code's Bedrock binding) is a guest-runtime / range
> concern tracked separately from this image-build pipeline.

### Other GCP image concepts (unchanged)

- **GDC VM Runtime** - OS images stored in GCS, imported as `VirtualMachineDisk` CRDs. Image URLs configured in `GDCVMRuntimeConfig` (`GDC_*_IMAGE_URL`).
- **Scenario Pods** - Standard container images from Artifact Registry.
- **VM-Series NGFW** - OVA image stored in GCS, bootstrapped via GCS bucket.
- **Control-plane containers** - Built once for each release by `release-gcp.yml` and pushed to the release registry; `gcp-deploy` copies them into the deployment Artifact Registry. A CI deploy through `_gcp-dev.yml` builds them directly into the deployment Artifact Registry.

See [GDC Provisioning](gdc-provisioning.md) for details.
