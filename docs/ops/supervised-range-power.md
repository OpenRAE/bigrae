# Operate supervised range power

The participant control service is an optional GCP installation component. It
runs one persistent worker with a retained volume and the released RAES owner.
It serves the authenticated management API and a separate private invocation
protocol. The ordinary portal process cannot create a temporary control owner.

## Deployment inputs

Follow the existing [GCP deployment handbook](../technical/handbook/gcp-github-less-deployment.md).
The installation's `participant_control` settings contain:

| Setting | Purpose |
| --- | --- |
| `enabled` | Explicit opt-in; defaults to `false`. |
| `tls_secret_name` | Existing Kubernetes TLS Secret in the platform namespace. |
| `trust_ca_pem` | Public PEM certificate bundle used to verify worker TLS. |
| `storage_class_name` | Storage class for the worker's retained volume; empty uses the cluster default. |
| `storage_gib` | Volume size, from 1 to 128 GiB; defaults to 8. |
| `max_contexts` | Concurrent retained owners, from 1 to 32; defaults to 8. |
| `idle_seconds` | Idle owner eviction interval, from 30 to 3600 seconds; defaults to 300. |
| `budgets` | Finite SDK admission, execution, observation, commit, and drain durations in milliseconds. |

The TLS Secret must contain `tls.crt` and `tls.key`. The certificate must cover
`participant-control.<platform-namespace>.svc`. Manage its private key through
the existing secret procedure. Installation configuration carries only the
Secret reference and public trust bundle.

The deployment derives the namespace and immutable worker and provisioner image
references from the verified release. Do not supply a provider module, custom
endpoint, storage path, or image through scenario content or API requests.
The Helm render refuses unsupported providers, missing network policy, missing
Kubernetes API egress addresses, and inconsistent image or namespace pins.

The storage class must support `ReadWriteOncePod`. The StatefulSet has one
replica. Its PVC is retained on deletion or scale-down. Back up and restore the
runtime files together with the corresponding native database state. Preserve
the original field encryption key needed for private compiler recovery.

The existing rollout path waits for the worker StatefulSet and verifies its
running image and support sidecars against the approved release. The worker
also verifies its live Pod identity at startup. An unhealthy or missing owner
causes control requests to fail closed.

## Recovery and maintenance

A compatible image or TLS trust rotation reopens the same native binding,
resource generation, run, episode, and original requests. Control policy budgets
are pinned separately. Changing them cannot silently reopen an old binding.
Stop and drain the original process before replacing its ownership. Never run
an extra replica or copy the store into a new owner to bypass its lock.

If an initialized run's runtime history is missing, restore that history. The
worker refuses to create a replacement episode for the same run. A successful
SQL binding lookup alone is insufficient to recover portable history.

An issued provider-call grant remains uncertain after a lost worker or response.
The recovery loop first fences later dispatch. It can close an uncertain grant
only after matching a completed GCE zonal operation to the exact request,
instance identity, operation type, and target. A missing Job, elapsed deadline,
or missing cloud history does not establish that the call stopped. Recovery
never resubmits a cloud mutation and never marks a range ready.

The readback worker uses the existing workers cloud identity with the additional
read permission `compute.zoneOperations.list`. Power mutation remains with the
provisioner identity. Projected provisioner tokens have a dedicated audience and
are checked against the actual Job, Pod, running container, and attempt.

Before any cloud-call permission is issued, failed SDK admission or accepted
cancellation can retract native delivery and restore the actual previous status.
The command fence prevents a late callback from recreating it. Once permission
has been issued, cleanup preserves uncertainty and requires cessation evidence.
Neither cancellation nor credential revocation proves rollback.

For emergency containment, use the existing authorized range destroy operation.
It can fence old power work without borrowing the original actor's authority.
Control routing can retire only after accepted current-generation destruction
and independent scoped inventory prove that the resources are absent. Historical
native authority and correlation rows remain retained.

## Qualification limits

The installed path uses RAES 10.6.0 API-409 v2 human supervision and independent
API-423 participant crossing mediation. API-424 modular mechanisms, arbitrary
adapters, AWS parity, and stronger guarantees are not advertised.

Tests exercise authenticated native services, the released runtime, private
workload grants, native result application, and released contract validators.
Cloud and guest edges in those tests are synthetic. They do not establish a
successful deployed cloud exercise, general conformance, or representative load
qualification. Issue #1969 extends the real deployment evidence.

See the [user guide](../features/supervised-range-power.md) and
[architecture design](../architecture/raes-participant-control-adoption-1968.md).

## Live acceptance sequence

Issue #1968 remains unqualified until an installed service and its actual
workload identity complete a real participant/world operation. The local joined
pipeline test supplies regression evidence, rather than that deployed proof.
The wider interruption, replay, recovery, and isolation program in #1969 does
not replace this initial requirement.

Use only an explicitly approved nonproduction tenant and an expendable range.
Keep its identifiers and operational evidence out of this public repository.

1. Publish the candidate through the approved signed test-release procedure.
   Preserve review and release gates; obtain approval for any change to their
   order before publishing or patching a test deployment.
2. Enable the fixed worker using the existing installation settings. Verify its
   actual image, Pod identity, service account, private TLS, retained storage,
   and normal release readback.
3. Install a synthetic source through the tenant's existing pack procedure.
   Verify the exact released contract, logical mapping, source and configuration
   digests, and the range's complete GCE VM and dedicated disk identities.
4. Through the authenticated participant control API, record a proposal, human
   approval, and action. Retain references to the tenant, assignment, binding,
   participant, episode, run, resource generation, current cut, native operation,
   SDK receipt, and workload invocation.
5. Verify the actual Kubernetes TokenReview and running Job/Pod/container identity.
   Confirm that strict native audit committed before the single provider call.
6. Read the GCE VM and disk identities independently and verify the requested
   power state. Confirm complete native result application for the same generation.
   Validate the retained records with the released RAES validators in their
   protected owner context; retain only permitted evidence and bounded references.
7. Revoke the relevant native permission for a separate reviewed request. Confirm
   refusal before any provider mutation, truthful native status, and audit.
8. Restore the approved tenant state and clean up only the test's owned resources.

Record the deployed revision and image digests, the exact procedure, observed
results, limitations, and the private evidence location before claiming readiness.
