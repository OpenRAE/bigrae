# GDC Range Provisioning

Range guest provisioning on Google Distributed Cloud (GDC). GDC uses KubeVirt for VM workloads and Kubernetes-native networking for guest isolation.

On AWS, ranges are EC2 instances in isolated VPC subnets. On GDC, ranges can be KubeVirt VMs or lightweight pods on a GDC cluster, connected via custom L2 networks.

**Status: non-user validation only; no live-fire approval (ADR-030).**

GDC VM Runtime, scenario Pods, and L2 Networks do not provide an approved live-fire containment boundary.
Live-fire participants and agents can run arbitrary activity.
GCE VM range cells are the default GCP live-fire backend (`GCP_RANGE_BACKEND=gce`).

CMS rejects normal Mission Control and CTF launches on GDC.
The provisioner independently rejects live-fire GDC apply calls (issue #1348).
Retained deterministic demo/BAS and operator-validation modes require an explicit trusted instantiation purpose.
Their evidence does not establish live-fire containment.
Policy admission also does not establish RAES realization support.
See [Range Instantiation Policy](range-instantiation-policy.md) for independent admission and capability checks.

## Runtime Primitives

The provisioner supports three GDC runtime primitives:

| Type | Module | What It Creates | Use Case |
|------|--------|----------------|----------|
| **VM Runtime** | `gdc_vmruntime_assets.py` | `VirtualMachine` + `VirtualMachineDisk` CRDs | Full OS guests (Kali, Ubuntu, Windows, Domain Controller) |
| **Scenario Pods** | `gdc_scenario_pods.py` | Kubernetes Pods with network attachments | Lower-fidelity container execution where full guest semantics are not required |
| **VM-Series NGFW** | `gdc_vmseries_ngfw.py` | VM-Series firewall VMs on GDC VM Runtime | Palo Alto Networks NGFW integration |

Current direction:

- live-fire GCP ranges (Mission Control, CTF) run on **GCE VM range cells**, not
  on the GDC VM Runtime path; see the status note above and ADR-030
- the GDC VM Runtime path is retained for operator/development validation of GDC
  scaling and admission behavior only
- pod execution is an internal optimization/runtime mode, not an author-facing scenario contract
- mixed ranges are valid when the provisioner determines different runtimes are appropriate for different guests on the same L2 network

## Network Provisioning

Module: `gdc_range_networks.py`

Each range gets isolated L2 networking:

1. **Network CR** - GDC `Network` custom resource defining the L2 segment (VXLAN-based)
2. **Network Attachment Definition** - CNI NAD for multi-NIC pod/VM attachment
3. **Subnet allocation** - Gateway IP + static IP reservations per subnet from a configurable range CIDR

Guest isolation comes from per-range namespaces and dedicated L2 networks rather than VPC-level isolation.

## VM Runtime Lifecycle

Module: `gdc_vmruntime_assets.py`

1. Create `VirtualMachineDisk` from GCS-hosted OS image
2. Wait for disk import to complete
3. Create `VirtualMachine` with disk, network interfaces, and cloud-init/userdata
4. Wait for VM to reach running state
5. Return IP assignments and connection details

Per-profile configuration (vCPU, memory, disk size, image URL) is defined in `GDCVMRuntimeConfig`. SSH keypairs are generated per-range.

## Scenario Pods

Module: `gdc_scenario_pods.py`

Lighter-weight alternative to full VMs. Pods attach to range L2 networks via CNI network attachment annotations. Lower resource overhead, but they are not the parity baseline for features that require full guest semantics.

## VM-Series NGFW on GDC

Module: `gdc_vmseries_ngfw.py`

Provisions Palo Alto Networks VM-Series as KubeVirt VMs with:
- Management + data network interfaces
- Bootstrap disk from GCS bucket
- SSH access via Secret Manager credentials
- Power operations (start/stop)

## Backend Ownership Binding (destroy-after-selector-flip)

`GCP_RANGE_BACKEND` selects which backend a *new* GCP range is admitted on (`gce`
range cells by default, or `gdc` VM Runtime for validation). It is a deploy-wide
selector, not durable ownership. CMS admission supplies the backend and trusted purpose.

Engine persists them as write-once `Range.range_backend` and `Range.instantiation_purpose` bindings at provisioning (#1666). Destroy, compensation, retry, and reconciliation use that binding through the request-scoped provisioner database projection. They do not reread the deployment selector.

Changing `gdc` to `gce` cannot redirect cleanup or strand GDC namespaces, VMs, disks, secrets, L2 Networks, or subnets.

Ranges created before #1666 carry no binding. On destroy the provisioner resolves
their backend only from durable ownership evidence (the `asset_type` discriminant
persisted on each instance's state: `vm_runtime_vm`/`scenario_pod` for GDC,
`gce_vm` for GCE range cells). Ambiguous or absent ownership produces `prerequisite` and preserves cleanup state. While the historical selector is known, backfill the binding explicitly before retrying:

Only an authorized operator may backfill a binding after reviewing durable ownership evidence.
Use an approved management-command transport; this example does not authorize production pod execution.

```bash
python manage.py backfill_range_backend_binding --request-id <uuid> --backend gdc
```

The binding is write-once: the command refuses to overwrite an existing value.

## Configuration

All GDC config is loaded from environment variables and Secret Manager at runtime. Key config structures in `engine/provisioner/config.py`:

| Config | Purpose |
|--------|---------|
| `GDCNetworkAccessConfig` | GDC cluster kubeconfig, VXLAN CIDR, namespace prefix, DNS |
| `GDCVMRuntimeConfig` | Storage class, image URLs and sizing per OS profile |
| `GDCPaloAltoVMSeriesConfig` | VM-Series image, bootstrap bucket, resource sizing |

GDC access credentials are stored in Secret Manager and loaded via `GDC_ACCESS_SECRET_ID`.

## File Locations

```
shifter/engine/provisioner/
├── gdc_range_networks.py      # L2 network provisioning
├── gdc_vmruntime_assets.py    # KubeVirt VM lifecycle
├── gdc_scenario_pods.py       # Pod-based guests
├── gdc_vmseries_ngfw.py       # VM-Series NGFW on GDC
├── config.py                  # Configuration dataclasses
└── templates/                 # Jinja2 templates for K8s manifests
```

## Related Docs

- [GCP Infrastructure](gcp-infrastructure.md) - GKE cluster and platform services
- [Cloud Adapters](../dev/cloud-adapters.md) - Protocol-based cloud abstraction
- [Networking](networking.md) - AWS VPC networking (parallel architecture)
