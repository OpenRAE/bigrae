# Disposable VM workers

Engine owns disposable workers through the native range lifecycle.
Each worker has one VM and one local Docker daemon.
Each worker has one immutable experiment reference and at most one trial reference.
The worker service accepts account scope and a current native credential.
Installation scope is unsupported.

The operator qualification command uses the existing recorded bootstrap administrator.
It obtains fixed, exact-target native credentials through Management, retains proof inside the process, and revokes it on each handled exit.
Application policy, personal-token eligibility, and customer membership remain mandatory.
Live qualification remains required before delivery.

## Apparatus and admission

An installation administrator publishes the worker policy through an authenticated service.
The policy contains global limits and one host profile.
The profile contains a validated outer RAES plan, an exact image profile and numeric provider image ID, provenance, resources, Docker version, capacity scope and partition, and approved egress.
This plan describes apparatus, separately from the experiment SDL.
The service supports the deployment-selected GCE backend.
Other backends fail before reservation or dispatch.
Policy changes affect new workers only.
An unchanged replay recovers retained custody and the original apparatus.
Database guards prevent bulk custody rewrites, trial reset, and deletion of the single-use worker record.
Workers retain the admitted profile for their complete lifetime.

The host plan has one Linux VM and one private network.
The existing RAES validator checks its realization contract.
The existing image profile validator checks its exact image and resource settings.
The immutable input carries the numeric image ID through the native image resolver.
Existing provider checks verify it before credential installation and against the actual boot disk.
The first worker path uses the existing E2 custom shape derived from the host plan.
The image profile cannot override that machine type.
This keeps physical CPU allocation consistent with capacity demand.
The host image supplies the pinned Docker version through standard guest bootstrap.
The service does not use the participant-container bootstrap contract.
Optional installed software uses an explicit apparatus binding to an installed adapter.
The adapter SDK distinguishes apparatus identity from pack identity.
The networkless planning Job and the provisioner action executor remain the executable boundary.

A singleton policy row serializes global count admission.
Provisioning, failed, held, retiring, and recovery workers count until verified provider absence.
Only accepted native readiness frees a provisioning slot before retirement.
Admission draws from an existing enforcing capacity reservation for the pinned resource demand.
Missing, expired, advisory, insufficient, or wrong-partition reservations refuse admission.
The catalog partition must match the deployment project, region, backend, and selected placement.
The administrator assesses the capacity scope through the existing capacity service before admission.
Active worker draws prevent reservation expiry and remain visible in shared headroom calculations.
Creation first commits worker custody, capacity draws, deferred native range creation, and strict audit together.
The worker then publishes its exact SQL parent through the existing authorization relationship port.
Publication retains the original store and model, and requires primary readback before native dispatch.
Unknown publication outcomes retain custody without launching a VM.
An identical create request can retry publication and dispatch.
The existing native launch outbox commits operation input, launch intent, and dispatch audit together.
A range lock fences retirement against this deferred dispatch.
Deferred dispatch takes ancestry, the worker policy mutex, and then the range lock, matching admission order.
This prevents lock inversion with another creation's exclusive native subnet allocator.
Provider calls remain outside SQL transactions.

## Identity, access, and retirement

The worker UUID is the native public range identity.
The composition root resolves worker scope through Engine before ordinary CMS scope resolution.
SQL supplies the exact parent and ancestry.
OpenFGA receives the corresponding native parent relationship.
The parent grants existing account administration permissions; experiment identity grants none.
Create uses parent launch authority.
Inspect uses range read authority.
Probe uses range access authority.
Holds and retirement use range manage authority.
The experiment reference conveys no permission.

Management access uses the private address, provider secret reference, and pinned host key from accepted range output.
Immutable operation input explicitly requests the management targets.
The provisioner returns their closed management projection separately from participant members.
Native member parsing keeps the existing count bound and rejects duplicate guest identities.
Engine validates the requested targets before it stores private generation-bound references.
Participant state and ordinary range projections contain no management credential reference.
The fixed probe addresses the local Unix Docker socket.
It checks daemon count, daemon ID, machine identity, and the pinned runtime version.
The service stores bounded qualification facts only.
It exposes no SSH material, provider output, or guest output.

Holds begin on ready workers.
Holds retain their principal owner, reason, creation time, and review deadline.
Multiple callers can hold one worker.
A caller can release its own hold.
An installation administrator can override an exact hold with strict audit.
Hold acquisition and retirement use the same native range lock.
Acquisition fails after destructive admission.
Native destruction and cancellation cleanup refuse active holds.
An overdue hold requires operator recovery; it does not permit deletion.

Reconciliation expires workers and retries cleanup with bounded backoff and a fixed attempt limit.
Exhausted recovery retains custody, pins, capacity, and an operator-visible obligation.
The operator can resume cleanup through the same service.
Only accepted absence evidence for the exact native generation releases capacity.
The native cancellation path handles an active provisioner.
The native cleanup retry path handles unknown terminal teardown.
Database protection prevents deletion of retained ownership through a range cascade.

## Data flow and security

```mermaid
flowchart LR
    Caller[Authenticated caller] -->|credential, scope, experiment, trial| Engine[Engine worker service]
    Command[Engine qualification command] -->|exact recorded operator| Management[Native Knox issuance and audit]
    Management -->|exact targets and fixed ceilings| Engine
    Command -->|handled exit| Revoke[Native credential revocation]
    Admin[Installation administrator] -->|validated apparatus policy| Engine
    Engine -->|custody, holds, draws, audit| DB[(PostgreSQL)]
    Engine -->|exact parent grant and primary readback| Policy[Existing OpenFGA provider]
    DB -->|immutable input and launch intent| Launcher[Existing launcher]
    Launcher -->|pinned operation| Provisioner[Existing provisioner]
    Provisioner -->|private management and owned resources| VM[Untrusted VM]
    Provisioner -->|closed results and provider absence| DB
    Engine -->|fixed probe over pinned private SSH| VM
    VM -->|bounded qualification facts| Engine
```

The control plane, provider, and guest are separate trust boundaries.
Current credentials and SQL ancestry prevent cross-account access.
Behavior tests exercise denied access, changed custody, and revoked proof.
The range lock prevents hold and destruction races.
Content pins prevent registry edits from changing admitted hosts.
Provider ownership checks protect shared infrastructure and other workers.
Capacity and count checks prevent oversubscription before effects.
Private NICs, existing firewalls, and pinned SSH keys protect management access.
The Docker socket remains inside its VM.
Guest output cannot select executable code or provider resources.
Strict audit records configuration, admission, holds, overrides, and retirement.
Errors contain fixed text and correlation identities.

Provider failures can retain resources and cost.
Recovery deadlines bound automatic work, rather than resource ownership.
A compromised guest can falsify its probe output.
Qualification proves synthetic management behavior, rather than experiment correctness.
Live qualification requires the approved GCP operating procedure and an approved target.

## Architecture model and references

`.importlinter` and `scripts/check_layer_imports/layer_imports.yaml` define the executable dependency model.
The updated composition allowance permits the worker ancestry resolver.
The layer-import checker enforces this model.
No new application, provider, public listener, or deployment environment is added.
Existing range containment and Job policies continue to apply.
The capacity and native hold fences extend their existing owning services.
The ADR registry records these extensions.

Reference evidence:

| Source | Version and section | Application |
| --- | --- | --- |
| [Django QuerySet API](https://docs.djangoproject.com/en/6.0/ref/models/querysets/) | 6.0, select_for_update | Admission and hold locks |
| [Knox token lifecycle](https://jazzband.github.io/django-rest-knox/views/) | Installed Knox library, expiry and logout | Native proof and revocation |
| [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) | Deny by default, validate every request | Checks on server-side worker operations |
| [Django transactions](https://docs.djangoproject.com/en/6.0/topics/db/transactions/) | 6.0, atomic | Custody and durable dispatch |
| [Compute custom images](https://docs.cloud.google.com/compute/docs/instances/create-vm-from-custom-image) | Compute Engine, image creation | Exact host image and independent VMs |
| [Compute custom machine types](https://docs.cloud.google.com/compute/docs/instances/creating-instance-with-custom-machine-type) | Compute Engine, E2 limits | Resource bounds and exact capacity demand |
| [Docker system info](https://docs.docker.com/reference/cli/docker/system/info/) | Engine CLI, format | Local daemon identity and runtime version |
| [ASD-STE100](https://asd-ste100.org/) | Issue 9, sections 1, 5, and 6 | Vocabulary, sentence length, and document purpose |

The RAES 10.6.0 public contracts and installed source define host plan validation.
The adapter SDK defines bounded input, planning, and guest actions.
`bigrae.runtime-plugin/v2` requires apparatus identity and forbids pack identity.
The existing version 1 contracts continue to require pack identity.
The design also follows the [worker boundary](../../architecture/disposable-trial-workers-boundary-2741.md).
