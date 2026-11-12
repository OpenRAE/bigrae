# GCP GCE range-cell deploy runbook

Part of the BigRAE deploy and operations docs; start at the [documentation home](../index.md).

The GCP range backend defaults to the GCE range-cell path, the approved GCP
live-fire backend (ADR-030). This runbook covers enabling it in a real
environment and mapping images.

For the backend design see
`docs/_deprecated/architecture/gcp-range-cell-backend-preflight-1341.md`. For image builds see
`docs/architecture/gcp-guest-images.md`.

## Backend selection

`settings.range_cells.backend` in `bigrae.yaml` selects the GCP range backend.
The deploy renders it as the runtime key `GCP_RANGE_BACKEND`. A CI deployment
sets the `GCP_RANGE_BACKEND` variable instead. The values are:

- `gce` (default): provision each range as an isolated GCE range cell. This is
  the only approved GCP **live-fire** backend (ADR-030).
- `gdc`: the retained GDC VM Runtime path (**development/validation only**). It is
  **not** a live-fire rollback: normal Mission Control and CTF range provisioning
  fails closed on `gdc` (the CMS service gate rejects the launch and the
  provisioner independently denies a live-fire GDC apply; issue #1348). Do not
  select `gdc` to "roll back" a live-fire environment when GCE is
  unhealthy. A GCE availability problem must be fixed on the GCE path, never by
  downgrading containment.

The default lives in the `settings.range_cells` model, `config.py`
(`get_gcp_range_backend`), and the generated runtime config
(`scripts/gcp/render_runtime_env.py`). The GDC configuration block
is retained in the rendered contract and is inert while the backend is `gce`.

### Switching the selector on an environment with existing GDC ranges

New GCP ranges persist the admitted `range_backend` and
`instantiation_purpose` as write-once Engine ownership state. Destroy and
provision, including artifact validation, variable shaping, configuration
loading, and provision-failure compensation, route from that per-range binding.
Changing the deploy-wide selector does not reclassify an existing range:
teardown continues to route from persisted ownership. A provision whose binding
no longer matches the selector fails closed rather than silently re-routing.
Both the legacy RangeSpec and RAES lifecycle paths require a valid persisted
backend/purpose pair and fail closed if it is absent or incompatible.

Legacy ranges created before the binding was introduced may have NULL ownership
fields. Their destroy path resolves only from durable instance-state evidence;
it never guesses from the current selector. If the evidence is absent or
ambiguous, cleanup fails closed and retains state. While the historical
selector is known, an operator can repair the row with
`manage.py backfill_range_backend_binding --range-id <id> --backend <gdc|gce>`
and retry. Do not switch selectors and then infer a legacy range's owner from
its scenario name, topology, or the backend that happens to be healthy.

The environment setting is an operator/backend-policy input for new
provisioning, not scenario metadata or ownership evidence for teardown. The
closed range-instantiation policy decides which launches may use each backend;
see
`docs/technical/platform_infrastructure/range-instantiation-policy.md`. An admitted GCP VM cell request cannot fall back to GDC, GKE, or legacy Terraform. Do not use `gdc` to recover a failed live-fire cell.

## Scenario-to-cell contract

This reference describes the retained Shifter cell and compatibility boundary.
Current authored scenarios use the pinned RAES contract through `shared.raes`.
`raes_gcp_apply.py` realizes the serialized RAES plan.
Retained `RangeSpec` readers do not establish another supported authoring language.

The boundary is the closed, versioned `shifter.gcp-vm-range-cell` contract in
`shifter/shifter_platform/shared/range_cells.py`. Its responsibilities are:

- The scenario producer owns VM roles/count, container or nested-Kubernetes intent, topology, connectivity, ports/DNS, and fixed addresses. It also owns images, startup/bootstrap behavior, services, and validation. The existing
  wrapped `RangeSpec` is validated by its canonical Pydantic contract before the
  Engine persists it as an immutable SHA-256-bound artifact. The standalone
  provisioner verifies that producer-minted digest without loading the scenario
  schema graph; the platform does not copy scenario fields into a universal
  placement model.
- The platform owns admission, operation/cell identity, network allocations, isolation, resource membership/ownership, lifecycle/recovery state, logical access, and cleanup. Allocated CIDRs are bindings and are not written back into the
  scenario artifact. Destroy restores bindings from platform allocations when available. Otherwise it uses validated authored membership and deterministic resource identity. Request validation never requires a blank CIDR.
- The outer request and result reject unknown fields and versions. A digest or
  backend mismatch, malformed/duplicate membership, or missing/foreign network
  binding fails before any Compute Engine or Secret Manager mutation. Results
  reject dangling access targets and inline credentials, trigger cell cleanup
  if output validation fails, and expose credential references rather than
  credential values. Participant access is a closed scenario declaration keyed
  by authored member plus `ssh` or `rdp` channel. The result must match that
  declaration exactly. Participant SSH keys are distinct from host-management
  setup keys, and host/bootstrap credential references never enter the closed
  access result.

`gcp_range_cell_scenario.py` is the compatibility adapter for the retained
legacy `RangeSpec`; it owns role/image/host-access interpretation. A future
scenario artifact can use a new discriminator/version adapter while retaining
the same cell lifecycle contract. See
`docs/_deprecated/architecture/scenario-gcp-range-cell-contract-preflight-1344.md` for the
full boundary analysis.

### Capability failures and diagnostics

Capability checks run while rendering the closed request, before Compute,
Secret Manager, or bootstrap mutation. Their stable failure classes are:

- `unsupported-capability`: the composition needs an unimplemented GCE
  capability, currently NGFW range attachment or a configured image profile
  whose `bootstrap_capability` has no GCE realizer. Fix the implementation; do
  not retry on GDC or pods.
- `prerequisite`: the approved route lacks a required input. Examples include an absent exact image mapping or a promoted DC image whose DNS/NetBIOS metadata differs from authored intent. Fix configuration or the scenario artifact, then launch a
  new range.
- `identity-or-policy`: the persisted backend/purpose pair is not admitted for
  a normal live-fire range, notably `gdc` with `live_fire`.

The current built-in support/evidence projection is in
[`docs/scenarios/index.md`](../scenarios/index.md#gcp-vm-range-cell-support). It is documentation only; do not reproduce it as a scenario-ID branch or CMS
allowlist. Destroy renders with image and provision-capability checks disabled,
so a newly unsupported composition can still be cleaned up deterministically.

That recovery also tolerates a missing CIDR binding when
provision failed before allocation: deletion uses deterministic owned-resource
names and remains idempotent. For a command-grammar denial, check `restrict-provisioner-jobs` in the base and Helm policies. Both must accept the optional UUID-validated `--operation-id` suffix.

Do not disable admission or remove the suffix.

## Required configuration

Set the GCE range-cell inputs in the deployment input bundle:
`settings.range_cells` in `bigrae.yaml` and the image roles in
`range-images.json`
([GitHub-less GCP deployment guide](../technical/handbook/gcp-github-less-deployment.md#author-and-publish-the-deployment-input-bundle)). [GCE range-cell settings](#gce-range-cell-settings) lists each setting and its CI variable. The GCE deploy precondition requires `settings.range_cells.zone` and the `linux` image role.
Add other roles when the selected scenario needs them.

Add the other guest
image profiles that the authored topology requires. Guests receive a keyless, least-privilege model identity by default (ADR-064). The range host account has predict-only Vertex authority. Workload Identity attaches it without generating or delivering key material. Guests stay identity-less only when the broker
is the guest model path (`MODEL_BROKER_GUEST_VIP` set), which is optional
(ADR-067).

Plugin installation and compatibility are separate from range
readiness; see the
[external runtime boundary](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/external-scenario-runtime-design.md).

The deployment `bigrae.yaml` must also set
`settings.dynamic_secret_project_id` to the pre-existing, deployment-only
range-secret project. It may equal the platform project in the supported single-project topology.
A separate project is an operator-selected boundary, not a mandatory second project. Broker
model invocation may use that project, the platform project, or another
administrator-selected project while retaining separate least-privilege
identities. New guest, RAES/GDC, VM-Series
and VPN secrets use canonical deployment- and audience-prefixed names in that
project; persisted full references remain authoritative for guest access.

Direct guest provider credentials are retired. Applying the deployment removes
the old invocation service account and its provisioner key-admin grants. Revoke
any externally owned shared keys through their owner. Legacy range teardown
removes only the range's stored copies; it never reads or reissues provider keys.

When GDC access/image inputs are enabled, declare the
full versionless refs under `settings.provisioner_static_secret_refs`. Do not add
a broad Secret Manager role to compensate for a missing entry. The migration,
permission-probe, quota, audit-cost, and revocation procedure is documented in
[`platform/terraform/gcp/README.md`](https://github.com/OpenRAE/bigrae/blob/dev/platform/terraform/gcp/README.md#deployment-scoped-range-secret-project).

When `settings.range_cells.project_id` is empty, the runtime renderer sets
`GCP_RANGE_CELL_PROJECT_ID` to the project parsed from the range VPC self-link.
The range backend then targets the real range project.

### GCE range-cell settings

The GCP range backend is `gce` (GCE range cells). A deployment without GitHub
sets these non-secret inputs in `bigrae.yaml` (`settings.range_cells` and
`settings.participant_openvpn`) and in `range-images.json`. A CI deployment
sets them as GitHub Actions repository or environment **variables** (`vars.*`);
the CI adapter projects each one onto the same setting. `gcp-deploy` passes them
to the generated runtime config. Unset values fall back to the code defaults in
`config.py`. The CI adapter is described in [Retained GCP CI deploy adapter](gcp-ci-adapter.md).

`./scripts/bootstrap/deploy.py gcp-images --project-id <project> --store
gs://<bucket>` verifies the Kali, Ubuntu, and DC images that the release
selects, imports or reuses them, and writes their exact references to
`range-images.json`. Without `--store`, it prints the references; a CI
deployment sets the `GCP_RANGE_*_IMAGE` variables to them. The command needs no
`GCP_GCE_BASE_IMAGE_BUCKET`. Set these values by hand only to pin a specific
image outside that flow.

| Setting | CI variable | Required | Notes |
|---|---|---|---|
| `settings.range_cells.backend` | `GCP_RANGE_BACKEND` | no | `gce` (default), the supported native GCE range-cell backend. The legacy `gdc` VM Runtime backend is retired and removed root-and-branch in #2311. |
| `settings.range_cells.project_id` | `GCP_RANGE_CELL_PROJECT_ID` | no | Project the range cells provision into. Defaults to the project parsed from the range VPC self-link (`range_network_id`), so it is correct even while the control-plane `GCP_PROJECT_ID` is a deploy-overlay placeholder. |
| `settings.range_cells.zone` | `RANGE_NETWORK_ZONE` | yes | Compute Engine zone for range guests, for example `us-central1-a`. |
| `linux` role in `range-images.json` | `GCP_RANGE_LINUX_IMAGE` | yes | Full image or family URL for the default unkeyed Linux/host profile. |
| `dc` role in `range-images.json` | `GCP_RANGE_DC_IMAGE` | DC scenarios | Default unkeyed Windows domain-controller image, pre-promoted at bake time. Baked per-domain from `dc-prebaked.pkr.hcl` into family `shifter-<purpose>-dc` (see "Baking a new pre-promoted DC image" in `docs/dev/gcp-range-cell-deploy.md`). |
| None | `DC_DOMAIN_PASSWORD` | DC scenarios | **Sensitive.** Domain Administrator password the provisioner sets on the pre-promoted DC (`set_admin_password`). Must match the password baked into the DC image by `a2_setup.ps1` at bake time (its `-AdminPassword` default). Supply the GCP deployment config reference. The renderer forwards it to the provisioner Job through `_GCP_PROVISIONER_ENV_KEYS`. Missing configuration prevents DC password setup. |
| `kali` role in `range-images.json` | `GCP_RANGE_KALI_IMAGE` | scenario | Default unkeyed Kali image. Keyed guests use the structured map below. |
| `windows` role in `range-images.json` | `GCP_RANGE_WINDOWS_IMAGE` | scenario | Generic Windows guest image. |
| `settings.range_cells.image_key_profiles` | `GCP_RANGE_IMAGE_KEY_PROFILES_JSON` | keyed scenarios | Optional compact JSON map from exact `(linux|kali|windows|dc, ami_key)` to a complete GCE profile. Normal images use `source_image`, sizing, disk policy, and a typed capability. Preconfigured hosts use an exact `source_machine_image`, machine type, host login, participant container/account, the closed `participant-readiness/v1` contract, and a lowercase SHA-256 readiness-manifest digest. Any profile may opt into public TCP 80/443 with `allow_public_web_egress` (default false). Maximum 32,768 bytes and 64 entries. Unknown keys, unsupported capabilities, and malformed profiles fail before cloud mutation. Use an Actions environment secret when resource names or logical selectors are confidential; the deploy workflow prefers that secret over the repository variable. The value is runtime configuration, not a credential, and is emitted into the private platform ConfigMap. See `docs/dev/gcp-range-cell-deploy.md`. |
| None | `GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL` | not read | Keyless guest identity provides default-on direct Vertex access (ADR-064). It combines a predict-only role with host telemetry and uses Workload Identity without key material. The deploy takes it from the Terraform output `range_host_service_account_email`; set no variable. When the model broker is the guest path (`MODEL_BROKER_GUEST_VIP` set) guests stay identity-less instead. |
| `settings.range_cells.host_identity_pool_size` | `GCP_RANGE_HOST_IDENTITY_POOL_SIZE` | machine-image hosts | Number of Terraform-created `sh-range-host-<slot>` identities. Must equal `range_host_identity_pool_size`; zero disables preconfigured machine-image hosts. |
| `settings.range_cells.private_google_access` | `GCP_RANGE_PRIVATE_GOOGLE_ACCESS` | no | Set `true` so no-external-IP guests reach approved Google APIs (including Vertex for default-on model access) over Private Google Access. Leave it `false` when the model broker is enabled: broker-enrolled ranges refuse to provision with Private Google Access on. |
| `settings.participant_openvpn.enabled` | `RANGE_OPENVPN_ENABLED` | no | Set `true` to give participants an OpenVPN profile for their range's single participant-access target (ADR-039-R10). Projected onto `settings.participant_openvpn.enabled`. It also deploys the shared OpenVPN server pool (#2480): Terraform `openvpn_pool_enabled` follows this setting, and `gcp-deploy` creates the pool PKI and release record. Apply `global/cicd-oidc` first so the deploy identity holds the conditioned pool role. Defaults to `false`. See "Participant OpenVPN access" in `docs/dev/gcp-range-cell-deploy.md`. |

By default, guests use keyless, predict-only Vertex identities (ADR-064). Operators must enable each required model in its region and satisfy effective IAM and quota prerequisites. When the ADR-059 broker is enabled
it becomes the guest model path and guests stay identity-less, with an admitted
allocation and trusted one-use enrollment. Terraform retains removal of the legacy invocation identity, key-admin grants, and per-range keys. Revoke externally managed shared keys through their owner before declaring migration complete.

## Network mode

`GCP_RANGE_CELL_NETWORK_MODE` selects how range guests are networked:

- `shared-vpc` (default): each range gets its own subnet in the pre-existing,
  platform-peered range VPC (`RANGE_NETWORK_ID`/`RANGE_VPC_ID`). This mirrors the
  AWS shared-VPC + per-range-subnet model, so the provisioner reaches guests over
  the existing platform↔range peering. Isolation is by per-range subnet and
  target-tag firewall rules (see `docs/architecture/range-isolation-model.md`).
  Requires `RANGE_NETWORK_ID` (or `RANGE_VPC_ID`); both are rendered from the
  `range_network_id` Terraform output.
- `vpc-per-range`: each range mints its own isolated VPC. This gives VPC-hard
  isolation but currently has **no provisioner reachability path** (no peering or
  IAP is created), so guests are unreachable and ranges cannot reach READY. It is
  retained as a selectable mode for a future peering/IAP implementation; do not
  use it for live deployments yet.

### Shared-VPC NAT capacity and event egress

Provider limits were checked on 2026-11-09; confirm actual quota and address headroom before an event.

Non-zero-egress range subnets are enrolled explicitly in a provisioner-owned
regional Cloud Router/NAT. The provisioner serializes Router changes and removes
each subnet from NAT before deleting it. This Router is separate from the
Terraform-owned migration-bridge NAT; do not configure both to cover the same
subnet.

A `none` range is never enrolled, and a conflicting all-subnet NAT
causes admission to fail rather than relying on a firewall-only deny. An existing range whose already-created subnets are still explicitly listed on
the Terraform bridge can replay without duplicate NAT enrollment. Before
destroying such a range, remove those subnet links from the Terraform bridge
through that environment's deploy; destroy refuses while the bridge
still owns them.

New subnets are never admitted onto the bridge.

[Cloud NAT limits](https://docs.cloud.google.com/nat/quota) allow 50 explicit subnet ranges per gateway and 50 gateways per Router. A VPC permits five Cloud Routers per region. The provisioner uses one regional Router and distributes explicit subnets across its gateways.

Count subnets per range, including recovery spares, rather than participants alone. The theoretical ceiling is 2,500 explicit subnets, not a guaranteed event size. [NAT ports/IPs](https://docs.cloud.google.com/nat/docs/ports-and-addresses), subnet space, VMs, addresses, image launch rates, and event capacity may limit it first.

Review provider quota and NAT utilization before a
large event; shared NAT is a regional failure domain. Correct capacity or scope failures at the source/configuration boundary. Do not add all-subnet NAT or a one-off firewall rule.

The CTF event workspace supplies egress policy for participant and managed-spare launches. Each range retains its participant/spare account ownership and authorized workspace binding. Workspace policy
changes are audited and affect subsequent range reservations only. Launched ranges retain their pinned mode. A recovery spare with a different event mode is refused before participant-range teardown.

### Range egress allowlist

The GCP range network egress allowlist is rendered from the deployment's
`bigrae.yaml`. `gcp-deploy` writes it into its private `settings.auto.tfvars`,
separate from the operator's Terraform values. Two Terraform variables expose
the platform contract:

| Variable                       | Type           | Meaning                                                                          |
| ------------------------------ | -------------- | -------------------------------------------------------------------------------- |
| `range_egress_mode`            | `string`       | One of `status-quo` (default), `deny-all`, `allowlist`                           |
| `range_egress_allowed_cidrs`   | `list(string)` | CIDR allowlist when `range_egress_mode = "allowlist"`                            |

The committed `terraform.tfvars` baseline sets `range_egress_mode =
"status-quo"`. Deployments that want enforcement set
`settings.range_egress` in `bigrae.yaml`; the deploy renders it into the
private var file that loads after the operator's values.

- **CI (`_gcp-dev.yml`)** renders the bundle from `SHIFTER_CONFIG_GCP_DEV`;
  `gcp-deploy` renders the egress variables.
- **A deployment without GitHub** keeps `bigrae.yaml` in its config bucket;
  `gcp-deploy` renders the same variables.
- **Local `terraform` runs** use the operator workflow in
  `docs/architecture/range-egress-ip-allowlist.md` (run `bigrae-config render`
  by hand, then `terraform apply`).

`bigrae.yaml` contains secret references, not values. It remains the authoritative deployment configuration. Store it as the protected CI payload rather than maintaining a second allowlist. Do **not** also set
`range_egress_mode` / `range_egress_allowed_cidrs` in the Terraform values;
that re-introduces the drift this flow removes.

### Range audit telemetry

Range subnets get VPC Flow Logs and range NAT gateways get Cloud NAT logging by
default. The platform project also logs Vertex AI Data Access calls. Change
these controls with `settings.range_telemetry` in `bigrae.yaml`. The deploy
verifies them after Terraform apply. See
[GCP range audit telemetry](../ops/gcp-range-audit-telemetry.md).

## Legacy RangeSpec image mapping

The scenario-owned legacy `RangeSpec` adapter resolves current instances to one
of four approved image profiles by role and OS (`GCERangeCellConfig.get_profile`):

| Instance | Profile | Runtime key |
|---|---|---|
| Domain controller (`role=dc`) | dc | `GCP_RANGE_DC_IMAGE` |
| Kali / attacker | kali | `GCP_RANGE_KALI_IMAGE` |
| Windows guest | windows | `GCP_RANGE_WINDOWS_IMAGE` |
| Everything else (Linux host) | linux | `GCP_RANGE_LINUX_IMAGE` |

The deploy sets each runtime key from the role of the same name in
`range-images.json`. A CI deployment sets the key as a variable.

Instances without an `ami_key` continue to use those four defaults. An instance
with an `ami_key` requires an exact entry in
`GCP_RANGE_IMAGE_KEY_PROFILES_JSON` (`settings.range_cells.image_key_profiles`)
under its derived profile class. Each entry
is complete.

Normal image profiles declare image, machine type, disk size, disk
type, and typed bootstrap capability. Exact machine-image profiles declare the
machine image, machine type, host-management login, participant
container/account, participant-readiness contract, and the immutable image's
readiness-manifest digest. Pre-promoted domain profiles also declare their baked
DNS and NetBIOS identity.

Unknown keys or keys in the wrong class fail before Compute or secret-client creation. They never fall back to a default role image. The adapter routes host access and bootstrap from this
trusted profile metadata, never from a scenario or image-name literal.

Profiles resolved for either legacy `RangeSpec` instances or RAES nodes that
require participant web research may set
`"allow_public_web_egress": true`. The range-cell backend then adds a
range-owned egress rule allowing only TCP 80/443 to public IPv4 through the
shared VPC's Cloud NAT. The default is `false`; the per-range default-deny rule
remains in place, and unrelated profiles receive no public egress allowance.
For an administrator-selected runtime-plugin image, set the same option on the
GCP target image profile in the pack assignment UI. It is pinned with that
assignment for new ranges; existing ranges keep their original egress posture.
AWS target profiles cannot use this GCP option.

The value is a non-secret JSON object, limited to 32,768 bytes and 64 total
entries. Profile classes and fields are closed. Logical keys must be lowercase
letters, digits, and hyphens. For example:

```json
{
  "kali": {
    "example-desktop": {
      "source_image": "projects/PROJECT/global/images/example-desktop-v1",
      "machine_type": "e2-standard-4",
      "disk_size_gb": 80,
      "disk_type": "pd-balanced",
      "bootstrap_capability": "standard"
    }
  },
  "dc": {
    "example-directory": {
      "source_image": "projects/PROJECT/global/images/example-directory-v1",
      "machine_type": "e2-standard-4",
      "disk_size_gb": 100,
      "disk_type": "pd-balanced",
      "bootstrap_capability": "prepromoted-domain-controller",
      "domain_dns_name": "example.test",
      "domain_netbios_name": "EXAMPLE"
    }
  }
}
```

The supported bootstrap capabilities are `standard`,
`prepromoted-domain-controller`, and
`preconfigured-machine-host`. Other well-formed capability values remain
parseable so the adapter can return the stable `unsupported-capability` result
when a scenario selects them.

An exact machine-image entry uses this conditional shape:

```json
{
  "kali": {
    "nested-host": {
      "source_machine_image": "projects/PROJECT/global/machineImages/nested-host-v1",
      "machine_type": "n2-standard-8",
      "bootstrap_capability": "preconfigured-machine-host",
      "participant_container_name": "participant-desktop",
      "participant_username": "operator",
      "participant_readiness_contract": "participant-readiness/v1",
      "participant_readiness_manifest_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "host_ssh_username": "hostadmin",
      "host_ssh_port": 2222,
      "allow_public_web_egress": true
    }
  }
}
```

Machine-image profiles inherit captured disks only. Clone requests replace
metadata, network interfaces, external-IP posture, identity, labels, tags, and
machine type. Every attached disk is set to auto-delete after create and again
before destroy. The image must publish its participant RDP endpoint on host port
3389 and create `/run/shifter/preconfigured-range-host.ready` only after its
contained workload is ready. That marker proves boot liveness, not participant
readiness. After installing the participant credential, the provisioner runs

`/usr/local/libexec/shifter-participant-readiness --contract participant-readiness/v1 --manifest-sha256 <digest>`

inside the configured container as the configured participant user. The image
owns that fixed executable and manifest. It must exercise the real browser launcher with disposable state.

Check browser trust, startup state, clean home, and projected material. Emit no sensitive output. Return nonzero on mismatch.

BigRAE discards its output and exposes only bounded pass/failure
codes. The marker alone cannot qualify a fresh participant profile. Require immutable-image, participant-canary, content-readback, egress, and shared-service evidence before handoff.

See `docs/_deprecated/architecture/nested-ctf-participant-readiness-preflight-1910.md`.

Bind qualification to the exact machine image, profile key/fingerprint, canary contract, and manifest digest. Include content-readback and participant-canary reason codes. Record opt-in web rules, regional NAT, and a non-opt-in negative. For historical broker qualification, include generation-bound model grants, broker destination/invocation identity, and post-destroy revocation. Keep
URLs, CA material, mission content, model bodies, receipt bytes, guest output,
IAM policy dumps, and provider response bodies out of that evidence. The current
boot marker alone is not a release qualification record.

`prepromoted-domain-controller` profile is usable only when both domain fields
match the scenario's `dc_config` (case-insensitively, with an optional trailing
DNS dot).

The provisioner records a bounded key/profile fingerprint on each new VM and
in existing provider metadata. Reconciliation rejects a keyed same-name VM if
that binding differs from the current plan. Destroy remains independent of the
mapping. Configure the keyed map and test keyed and unkeyed launches. Then restore generic default Kali/DC families after any temporary scenario-specific override. Cross-project image families require the
narrow image-project grant for the provisioner GSA; do not broaden portal or
launcher identities.

Images are native GCE images. A reference names an exact image
(`projects/<project>/global/images/<name>`) or a family
(`projects/<project>/global/images/family/shifter-<type>`). `gcp-images` records
exact image references. Unlike the GDC path there is no qcow2 export or CDI
import.

## Service accounts

By default, range guests receive a keyless, least-privilege model-access
identity (ADR-064). The range host account has `aiplatform.endpoints.predict` in the platform project. Guests obtain it through Workload Identity. It grants no cloud management, storage, secrets, peer-range, or portal authority. Exact preconfigured machine-image profiles use the bounded range-host
identity pool selected by the range allocation slot.

Historical broker and keyless-direct modes are mutually exclusive per range. With `MODEL_BROKER_GUEST_VIP`, the provisioner leaves guests without an attached identity. Otherwise it attaches the keyless identity.

ADR-068 parks the broker; do not enable it from this retained compatibility description. ADR-067 does not require broker enforcement. Keyless-direct is the default for all ranges, including CTF; ADR-068 keeps broker operation unsupported.

No provider service-account
keys or shared model keys are minted into guests; legacy key revocation remains
part of teardown.

## Participant OpenVPN access

Participants can reach their range through a native OpenVPN client instead of
the browser (ADR-039-R10). The range-access page offers an `.ovpn` download; the
tunnel reaches exactly one range member, the scenario's participant-access
target, and only on its declared participant channels (SSH 22, RDP 3389). Every
other range member is reachable only by attacking the range from that target.

Every participant connects to one shared OpenVPN server pool per deployment
(#2480), not to a per-range gateway:

- A regional managed instance group of Container-Optimized OS VMs runs outside
  the GKE cluster, in its own subnet of the range VPC (`openvpn_pool_subnet_cidr`,
  default `10.49.0.0/24`). The VMs have no public addresses.
- One external passthrough load balancer on a reserved address is the only
  listener: UDP 1194, mutual TLS with tls-crypt. Every profile names that
  address. Client-IP affinity keeps a client on one server.
- Before a server admits a client, it asks the portal. The portal admits the certificate only for a `READY` range with matching owner and generation before the access deadline. One session is active per range; a new connection replaces the old one. Admission returns the target address and ports.
  The server then allows that client to reach only that address and those ports
  and pushes only that route.
- Clients ping every 5 seconds and reconnect after 30 seconds of silence, so an
  unplanned server loss costs about 30 seconds. A server that is stopped (deploy,
  scale-in, replacement) tells its clients to reconnect immediately.
- Servers renew their sessions every 15 seconds. Destroy, pause, owner change,
  the deadline, or a newer session disconnects a tunnel within one heartbeat. A
  server that cannot confirm its sessions with the portal disconnects every
  client after 90 seconds.
- A range with OpenVPN admits the pool subnet only to its target node, on its
  declared channel ports.

Enable it per deployment:

1. Apply `platform/terraform/gcp/global/cicd-oidc` for the deployment's identity
   profile from a revision that includes the pool. The apply adds the deploy and
   destroy roles `<prefix>_deploy_vpn_pool` and `<prefix>_destroy_vpn_pool`.
   These roles cover the pool's templates, regional instance group, and
   autoscaler. VM, disk, and template permissions are limited to
   `shifter-<environment>-vpn-` names. Without these roles the deploy fails when
   it creates the pool's instance template. Confirm both bindings:

   ```bash
   gcloud projects get-iam-policy <project> --format=json \
     | jq -r '.bindings[] | select(.role | test("vpn_pool")) | .role'
   ```

2. Set `settings.participant_openvpn.enabled: true` in `bigrae.yaml` (default
   `false`), publish the bundle, then run `gcp-deploy`. A CI deployment sets the variable
   `RANGE_OPENVPN_ENABLED=true` and runs the CI deploy. The deploy creates the
   pool, the tenant OpenVPN CA, the pool server certificate, and its release
   record. It records the scanned digest and starts the servers. Every server
   must become healthy behind the load balancer. It renders the pool wiring into
   the runtime environment.
3. Plan quota for the pool: the pool adds `e2-standard-2` VMs with two vCPUs
   each, up to the profile maximum. It also needs one endpoint address and one
   NAT address.
4. Size the pool through `settings.shared_service_capacity_profile`. Each profile plans 25 participants per `e2-standard-2` server and one spare server. It scales out at 30% CPU and permits twice the minimum server count. Check
   the live values with `scripts/gcp/check_event_capacity_drift.py --vpn-pool`.

Do not set `openvpn_pool_enabled` in the Terraform values. The command sets it
from `settings.participant_openvpn.enabled`. Launches stay safe either way: the
runtime switch is off unless the deploy renders `RANGE_OPENVPN_ENABLED=true`,
and that render fails if no pool exists.

Each deploy scans the pool image of its release and records its digest. A CI
deploy builds that image in the same run. A deployment without GitHub uses the
image that its release built. When the digest or the server certificate
changes, the deploy replaces the servers by surging new ones in before old ones
leave. Connected participants reconnect once, like browser sessions during the
control-plane restart. The
deploy also creates the tenant CA once and renews the pool server certificate
30 days before it expires; private keys never enter Terraform state.

Warm-pool generations carry no VPN; a claim mints the claimant's profile. A CTF
spare uses the event owner's principal without a fabricated login identity. That principal can authenticate, including when it is human.

A spare receives no participant VPN delivery until recovery binds the exact participant. Replace and revoke any previous profile before delivering its new binding. A range whose owner could have downloaded a live profile never changes
owner in place without that revocation boundary.

EC2 is tracked
by #2481.

## Baking a new pre-promoted DC image

Domain controllers are **pre-promoted at bake time** so a range boots an
already-promoted DC with no per-range promotion (promotion takes ~15-20 minutes
and would dominate time-to-serve). One parameterized Packer template,
`shifter/packer/gcp/dc-prebaked.pkr.hcl`, bakes many DC images. At range setup
the DC is only **verified** (that it is already the expected promoted domain),
never promoted.

Runtime DC mutation is **disabled and unreachable**. Two paths are locked off,
each retained as code for a future, explicitly authorized decision but selectable
by nothing:

- **Runtime promotion**: `_should_promote_dc_at_runtime` always returns `False`
  (no provider default, no `DC_RUNTIME_PROMOTION` env escape hatch). A DC image
  that is not actually pre-promoted fails verification at setup rather than
  silently promoting.
- **Runtime bootstrap/rename**: `_should_run_dc_bootstrap_plan` always returns
  `False` (no provider default, no `DC_BOOTSTRAP_VIA_SETUP_PLAN` env escape
  hatch). A DC `BootstrapPlan` rename would change a promoted DC's AD identity. Instead, the provisioner establishes SSH through guest startup metadata for host keys and `administrators_authorized_keys`.

The generic template requires an explicitly selected profile containing the DNS
name, NetBIOS name, image purpose and content seed path. The checked-in example
profile documents these inputs; there is no private default. Core's image build
workflow rejects missing or unknown profiles before cloud authentication.

Pack-specific profiles, content seeds, container stacks and image recipes belong
in the pack owner's repository and build pipeline. Publish their exact image
identities through the supported image/preparation contract. Do not add a pack
name to core workflow choices or dispatch on an image alias in the provisioner.
The consuming scenario's domain intent must match the baked image identity.

## NGFW

There is no GCE-native NGFW (Palo Alto VM-Series) path; that path exists only
under the GDC backend. A GCP range that requests an NGFW is not supported while
the backend is `gce`.
