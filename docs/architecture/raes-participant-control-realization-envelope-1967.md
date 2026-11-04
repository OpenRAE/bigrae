# RAES Participant-Control Realization Envelope

Status: accepted architecture guidance; participant-control integration pending

Implementation design for #1968:
[platform adoption, mechanism comparison, and released-RAES compatibility](raes-participant-control-adoption-1968.md).
The initial realization uses API-409 supervision and API-423 crossings.
API-424 modular effects are a separate, unsupported installation for this profile.
The implementation design is a Shifter decision; it requests no RAES changes.

Date: 2026-09-06

Tracking issues: <https://github.com/OpenRAE/bigrae/issues/1967> (selection),
<https://github.com/OpenRAE/bigrae/issues/1968> (implementation).

Implementation preflight refreshed: 2026-11-03, checkout `6dcaa6913`.

Portable authority: OpenRAE ADR-108 and
`participant-control-composition/rev1` (PC-01 through PC-15), accepted at
OpenRAE/rae revision
`ebb70a34b8e7d1cc8964c443841ae57e12ed1014`.

ADR: ADR-058. Shifter requirement: [GEN-2005](../requirements/GEN-2005/requirement.md).

Delivery and proof belong to #1968 and #1969. This decision selects a design;
it does not implement a control mechanism, widen a backend manifest, add a
schema, or assert released support. Native surface assessment includes Shifter
revision `9516f802385af56cfe9ea1b3b906aa0eb7dc0d8e`.

## Decision

Shifter selects one closed local profile for initial implementation:

| Identity field | Selected value |
| --- | --- |
| Local profile | `shifter-ctf-gce-range-lifecycle` |
| Profile version | `1` |
| Operating mode | CTF cyber-range, one event participant's current dedicated RAES range generation |
| Selected protections | Released explicit supervision plus native capability restriction, resource limits and strict audit |
| Approval provider | Explicit proposal-bound approval in the CTF product control decision by an actor whose current event authority is verified |
| Authorization provider | `ctf.services.authorization.assert_event_action` for exact `event.manage_ranges` (`EventCapability.RANGES` at the API), using current shared policy; CMS/Engine retain credential, target, scope, lifecycle, and generation authorization |
| Evidence sink | Request-attributed strict `shared.audit`; evidence is not approval or workflow state |
| Effect provider | ADR-039 `range-substrate/v1`, adapter `gcp-gce` |
| Native action set | whole-range `pause` and `resume`, with the persistent-resource limits below |
| Portable control path | API-409 proposal, approval/denial and cancellation; API-423 ingress and separately authorized disclosure |
| Native protections | Current permissions, complete resource limits and strict intent/outcome audit |
| Operation transport | Existing `shifter.provisioner-operation`; authority-bearing version `2` binds `authority_digest`, generation-fenced by `operation_id`; version `1` remains an incumbent compatibility contract |
| Portable interpreter/conformance boundary | `shared.raes`, using the exact released RAES contract and verdict implementation |

The mechanism-family labels above name the accepted RAES architectural
families; they are not new Shifter wire literals. `shared.raes` must consume the
actual identifiers, DTOs, versions, and verdicts from a released RAES artifact.
The Shifter-local profile tuple is application policy and must never be emitted
as a replacement portable participant-control schema. Its exact identity and
canonical digest, and the exact released mechanism, provider implementation,
and provider-configuration identities and digests, are admission bindings. They
cannot be filled with architectural family labels or the existing
provisioning-only `SHIFTER_REALIZER_CONFIGURATION` digest.

This composition fits Shifter because it already has an exact event-scoped
`CTFParticipant` to dedicated `RangeInstance` association, central organizer
authorization, a default-deny persistent-resource lifecycle capability check, a
persisted GCE range-backend binding, a durable generation-fenced operation path,
provider readback, and strict Engine result auditing. It does not depend on
mechanism parity with LilRAE.

An authored scenario may express portable RAES control semantics. It may not
name Python code, a service, a task command, a cloud adapter, a Shifter profile,
or a provider implementation. Shifter selects the exact local profile and
provider from closed server policy plus the persisted range binding. An unknown
mechanism/profile/version/effect/provider combination is unsupported and fails
before control-workflow persistence, launch, or provider mutation. A bounded
denial audit may still be emitted; it is not evidence that a control occurred.

Native pause/resume use an exactly bound admitted action through the released
participant-runtime adapter. API-409 owns proposal and decision history;
API-423 owns crossing admission and disclosure. Native permissions, resource
limits and strict audit remain BigRAE service responsibilities. Explicit human
review does not require an API-424 mechanism to schedule a request-review effect.

This #1968 amendment follows the approved source assessment and
[revised plan](https://github.com/OpenRAE/bigrae/issues/1968#issuecomment-6613801679).
[Hub #3](https://github.com/OpenRAE/hub/issues/3) establishes the responsibility
split. RAES drives portable semantics and runtime behavior; BigRAE realizes
those contracts through organizational services. The original requirement for
a closed API-424 mapping around every explicit approval is superseded.
Automatic modular review/audit effects and the original full modular profile
remain unsupported. They are not prerequisites of this supervisory use case.
No native action is relabeled as portable interrupt or shutdown.

### Research basis and alternatives

The [issue research record](https://github.com/Brad-Edwards/bigrae/issues/1967#issuecomment-5555762123)
contains the source inventory, methods, limitations and SDL lineage assessment;
the [accepted-authority update](https://github.com/Brad-Edwards/bigrae/issues/1967#issuecomment-5556555834)
supersedes its earlier status of #1068. These sources informed the selection:

- The RAES SDL lineage ledger distinguishes Open Cyber Range authoring/model
  ancestry from CyRIS provisioning, CybORG actor/action models, and
  CACAO/STIX/OCSF workflow, reference and telemetry influences. None is a
  compatibility promise. See the pinned
  [lineage ledger](https://github.com/OpenRAE/rae/blob/fb4cb4b7002305e7062bc51f1eda77c5852b2642/contracts/provenance/sdl-lineage-ledger-v1.json).
  Shifter's
  ADR-024 hard cutover remains binding; retired CyberScript is not an extension
  seam. The [RAES design-intent clarification](https://github.com/OpenRAE/rae/blob/fb4cb4b7002305e7062bc51f1eda77c5852b2642/docs/research/language-extensibility/design-intent.md)
  keeps author constraints separate from backend
  realization choices: a witness must satisfy the requested constraints, not
  silently substitute a weaker profile or force operator configuration into SDL.
  The associated ADR-105 is proposed, not authority to invent released SDL syntax.
- [Saltzer and Schroeder](https://www.cl.cam.ac.uk/teaching/1011/R01/75-protection.pdf)
  motivate complete mediation and least authority.
  [Schneider](https://www.cs.cornell.edu/fbs/publications/EnfSecPols.pdf)
  supports conjunction of applicable restrictions, not arbitrary effect
  composition. RAES PC-05–PC-10 supplies the latter's actual contract.
- [CaMeL](https://arxiv.org/html/2503.18813v2) and
  [Fides](https://arxiv.org/html/2505.23643v1) depend on mediated data/control
  flows and available provenance. Shifter's interactive access and guest
  execution do not establish that coverage. Dynamic IFC is therefore not
  selected; missing influence information is not an empty known label.
- Formal [shield synthesis](https://arxiv.org/abs/1501.02573v2) needs an
  observable property and enforceable intervention boundary.
  [ShieldAgent](https://proceedings.mlr.press/v267/chen25ae.html) supplies
  bounded empirical results, not that formal guarantee. Neither justifies an
  arbitrary in-guest runtime-shield claim here.
- Current work such as [AgentSpec (ICSE 2026)](https://ink.library.smu.edu.sg/sis_research/10278/)
  and [capability-oriented agent security (CAIS 2026)](https://www.yichenxu.me/files/publications/securing-agents/paper.pdf)
  reinforces explicit, limited enforcement boundaries; it does not establish
  Python/GCE realization or require a new Shifter policy language.
  [Prudentia (2026 preprint)](https://arxiv.org/html/2602.11416v1) makes approval
  cost and human supervision relevant limitations, not proof of reliable
  operator decisions.

The initial use is a deliberate session/resource intervention, such as
reviewing a teaching-session pause, not an automated attack detector. Capability
restriction, explicit review and bounded resource actions fit existing service
ownership and measurable GCE postconditions. Handoff, IFC and shielding lack
the selected identity/propagation/actuation coverage; they are not approximated
by an approval row, firewall, message or resource power operation. No mechanism
is selected merely because another backend uses it.

### Resource and memory limits

The native GCE adapter maps pause to stop and resume to start. Google's
[stop/start contract](https://docs.cloud.google.com/compute/docs/instances/stop-start-instance#stop_an_instance)
does not preserve RAM/application state as suspension does. This profile claims
only observed compute power state and the admitted persistent resources and
identity; it does not freeze a human participant, world clock, process,
network session or application. It does not reset portable participant memory
or erase history/influence. A request requiring stronger memory semantics is
unsupported, not silently narrowed.

Admission requires a nonempty, dedicated GCE member set whose complete mutable
footprint is within the bound participant resource scope. Version 1 excludes
Local SSD-dependent preservation, unobserved resources, automatic external
restart controllers, shared participant resources and any attached NGFW that
could enter the native lifecycle cascade. The existing helper's asset-kind
check is necessary but cannot establish these additional conditions. Keep
ADR-039 access unavailability/readiness checks; never disable platform
isolation or expand the admitted footprint to make pause/resume succeed.

## Declared World And Operating Envelope

The declared world is the participant, accounts, nodes, networks, and other
world resources present in the validated and compiled RAES scenario, narrowed
to the one current Shifter range generation that genuinely realizes them. For
the initial profile, the controllable unit is the complete dedicated range, not
an inferred individual RAES agent or an arbitrary VM selected by a caller.

The following are out of world and remain backend/platform security concerns:

- the Django control plane, PostgreSQL, workers, provisioner workload, and
  provider control APIs;
- organizations, workspaces, event authority, API tokens, sessions, and service
  identities;
- Shifter management cloud projects/accounts, IAM, KMS, secret and metadata services,
  management networks, range-isolation firewalls, and tenant boundaries;
- operation inputs/results, launch intents, audit rows, event outboxes,
  credentials, terminal/Guacamole brokers, and deployment configuration.

An attack on or protection of those surfaces is not a RAES world action,
observation, intervention, or participant-control effect. A control operation
must never weaken them or report their state as participant evidence.

This is an ownership boundary, not a ban on modeling a technology. Isolated
scenario accounts, test credentials or modeled directory/metadata services can
be in world when explicitly declared, admitted and realized there; they never
inherit management authority. ADR-056 containment and ADR-057's limited
control-plane transport claims remain independent prerequisites, not in-world
mechanism results.

| Environment class | Initial disposition |
| --- | --- |
| GCP/GCE CTF cyber-range | Supported only by the exact profile above after #1968 implementation and #1969 real-boundary proof. |
| Mission Control/non-CTF range | Unsupported: range ownership is not a trusted mapping to an individual RAES participant. |
| GDC non-user demo/BAS | Unsupported: it has no admitted participant workload and no selected control profile. |
| Simulated environment | Unsupported: Shifter has no simulation participant-control provider or readback boundary. |
| AWS range | Unsupported for this profile: no released and proven RAES participant-control realization is selected. |
| Federated environment | Unsupported: no controller handoff, remote trust, lease, revocation, or evidence protocol is selected. |
| Genuinely live/external environment | Unsupported: Shifter does not claim authority over external production actors or systems. |

These are limits of the selected Shifter profile, not a claim that RAES cannot
describe simulated, federated or genuinely live worlds. Such a world needs its
own admitted authority, provider, crossing coverage and evidence.

## Existing Surface Inventory

| RAES/control concern | Current canonical surface | Boundary for #1968 |
| --- | --- | --- |
| Portable RAES semantics | `shared.raes`; ADR-031 import confinement; exact `raes==10.6.0` and `raes-env-packs==7.2.2` pins in platform `pyproject.toml`/`uv.lock` | This release contains modular-control contracts, runtime and conformance tooling. Availability is not Shifter installation, admission or realization evidence. |
| Backend capability | `shared/raes/backend-manifest.json`, `shared.raes.manifest` | Currently `provisioning-only`; `participant_runtime`, `observation`, `orchestrator`, and `evaluator` are null. Existing sidecars do not widen it. |
| Participant semantics | compiled RAES participant behaviors and ADR-032-R10 `ParticipantAccessBinding` | Access is not control, and participant-invariant access is not participant identity. The initial control target comes from the event participant's current dedicated range binding. |
| Run/context identity | `shared.raes.runs.validate_run_binding` and bounded `RunDescriptor`; compiled plan persisted in Engine `Range.range_config` | Reuse released RAES validation and the one-way run-binding identity, but do not overclaim the incumbent: the descriptor is not currently persisted through range launch and establishes neither an active participant-control episode/controller nor a history cut. Those exact released-runtime identities must bind to the admitted compiled package/run and current range generation before control admission. |
| Product participant | `ctf.models.CTFParticipant`, event-scoped CTF services | A CTF participant, Django user, RAES participant, range owner, and runtime node remain different identities. |
| Action/effect execution | `ctf.services.range.lifecycle`, `ctf.bridges`, CMS `_scoped_range_lifecycle`, Engine `_principal_lifecycle` and `_lifecycle`, ADR-039 range substrate | Reuse the authenticated prepare/commit path for pause/resume. Native RAES ranges are currently rejected; enabling their lifecycle is required work, not an existing capability. Direct organizer range actions are not portable control occurrences. |
| Intervention | ADR-051 `CommunicationIntent` RAES provenance and CTF communication policy | Disclosure, external direction, and intervention remain distinct. A communication is not a control effect; an intervention needs the exact selected mapping and observed effect. |
| Observation/readback | `OperationResultInbox`, Engine result applier, `Range`/`Instance` state, `RangeEventOutbox` | Provider completion is true only after the current generation's closed result is validated and its complete target state is observed. Queue/task acceptance is not effect success. |
| RAES operation evidence | `RaesOperationRecord`, `shared.raes.operations`, `shared.raes.projections` | Reuse receipt/status/reference projections where the released contract permits; never add control semantics to JSON opportunistically. |
| Participant history/evidence | `RaesParticipantRuntimeRecord` and reference-only projection helpers | These local sidecars are not a portable participant-control DTO or workflow store. Do not add control requests, approval state, provider payloads, or verdicts to them. |
| Durable command | `ProvisionerLaunchIntent`, immutable `OperationInput`, canonical command validator | Reuse one generation-fenced launch path. Do not add a control queue or pass RAES payloads in task arguments. |
| Durable result | append-only `OperationResultInbox`, Engine-only applier | Reuse digest conflict, version, ownership, ordering, stale-generation, and result-shape checks. |
| Audit | `shared.audit`; strict Engine result audit | Approval/intent audit must become strict and durable before effect. `AuditLog` remains evidence, never queue or approval workflow state. |
| Notifications | ADR-025 `RangeEventOutbox` plus authoritative reconciliation | Status events are propagation signals, not portable observations or the control result store. |
| Errors/logging | `CMSError`, CTF domain exceptions, `shared.exceptions.ValidationError`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact` | Map at existing boundaries with stable reason codes; do not create a participant-control exception hierarchy or expose raw RAES/provider failures. |
| Verification | `tests/shared/raes` conformance/fixture style; CTF organizer authorization/audit tests; CMS lifecycle tests; Engine launch/applier/generation tests; provisioner pause/resume tests | Extend the existing vertical seams and negative matrices. #1969 adds disposable real-GCE effect/readback/isolation proof; mocks alone cannot release the claim. |

### Current checkout constraints for #1968

The modular-control constraints below apply only to a separately selected
API-424 installation. The initial supervisory path selects no such installation;
its own API-409/API-423 contracts, native protections and evidence gates apply.

These findings update the original surface assessment without changing the
selected mechanism or prescribing implementation steps:

- RAES 10.6.0 publishes `ParticipantControlProvider`/`ParticipantControlProviderV2`
  in `raes_backend_protocols.protocols`, `ParticipantControlRuntimeBinding` in
  `raes_runtime.participant_control_binding`, API-424 selection/evaluation
  contracts, and `raes_conformance.conformance.modular_control`. Local profile
  version `1` is independent of portable schema/protocol versions. Bind one
  compatible released family and its schema digests; the installed modular
  conformance runner uses `modular-control-runtime/v2`. Do not mix a v1 provider
  with v2 stages/probes or infer support from method presence.
- In API-424/v2, permit/deny/withhold are `ControlParentDecisionV2Model`
  dispositions, not executable `ControlEffectRequestV2Model` targets. Audit and
  request-review are separately admitted effects. Preserve that split when
  mapping the selected conceptual effects; do not put parent decisions into the
  executable-effect union or describe native stop/start as interrupt/shutdown.
- RUN-320 composition requires both the incumbent crossing-policy resolver and
  an API-407 `participant_modular_control` declaration. Shifter's manifest still
  has `participant_runtime: null`. An organizer HTTP request or GCE power call
  alone is not a participant/world crossing. Candidate proof needs an explicitly
  admitted configured target using the real released crossing boundary; preserve
  the generic provisioning-only claim until its replacement is evidenced. Reuse
  `shared.raes.manifest`/`contracts`, the checked-in manifest and the existing
  publication/conformance gates together; do not patch only the JSON artifact
  or bypass runtime capability admission to bootstrap a probe.
- Engine `get_range_pause_resume_capability` and `prepare_range_lifecycle`
  explicitly refuse native RAES plans. The CLI implements no `raes-range`
  pause/resume, despite the launcher/Helm grammar permitting those words.
  ADR-058 selects the existing `resource=range` lifecycle transport. Its current
  input builder carries legacy `range_spec`, and its worker classifies mutable
  `engine_instance` rows; neither supplies the complete generation-bound native
  RAES footprint. Extend the incumbent operation-specific input/consumer and
  result contracts consistently; do not parse a ProvisioningPlan as a legacy
  spec, revive retired CyberScript, or remove the denial without the missing gates.
- The current authority path carries `CredentialContext` unchanged from CTF,
  through CMS, into Engine. `assert_event_action` uses live shared policy;
  `resolve_event_authority` is the older user/role resolver and must not become
  an alternate permission store. ADR-066 `PrincipalRef`, `ResourceScope`,
  credential ceilings and SQL-owned event/range ancestry are canonical. Preserve
  human/service distinctions; a credential or policy permit is not a deliberate
  human approval, and participant membership grants no organizer authority.
- `PreparedRangeLifecycle`, `_launch_authority`, `_launch_authority_binding`,
  `shared.operation_authority` and `engine.launch_payload_authority` already
  bind/recheck the initiating proof, owner, scope, backend and
  `Range.resource_generation`. Reuse them. Resource incarnation, operation UUID,
  RAES episode and control state cut are separate identities. These commit and
  pre-launch checks do not fence each subsequent GCE call or prove revocation.
- The published `shifter_adapter_sdk.runtime` plugin capability set is only
  `guest.configure`/`guest.verify`. Its tenant-admin installation/binding and
  isolated worker paths are incumbents for external guest adapters, not modular
  control protocols or proof of control-provider installation. Implement trusted
  control resolvers through the released RAES provider boundary; do not overload
  guest actions, add a second loader, install pack code into the portal/provisioner,
  or pass platform/cloud authority into an isolated plugin worker.
- `audit_organizer_participant_range_action` is best effort;
  `admin_external_audit` remains an owner/staff no-op. Neither meets this profile's
  strict all-source decision audit. Existing strict CMS/Engine transition audit
  is reusable but is not proposal-bound approval or portable control history.
- P1 has no admitted Shifter embedding here yet. Reuse the released durable
  store/owner-lease implementation through `shared.raes`, with one immutable
  target/run per owner and storage outside the pausable world. A SQLite file in
  a stateless web worker, `/tmp`, a provisioner Job's `emptyDir`, or participant
  storage is not durable ownership. Store paths are installation-derived and
  must pass the released path/permission/symlink and ownership checks. Do not
  add arbitrary mounts to the hardened provisioner Job or invent a second store.

## Placement, Trust, Lifecycle, And Persistence

`shared.raes` owns portable parsing, exact profile compatibility, bounded
projection, released composition/conformance calls, and access to the released
authoritative runtime. It performs no product authorization or effect. That
runtime, not a Shifter sidecar or product model, commits portable control
history, provider-state transitions, finite causal budgets, effect claims, and
control dispositions. CTF owns event-participant resolution, the explicit proposal-bound
product approval, live `event.manage_ranges` authorization, and the local
occurrence-to-effect mapping. It reaches CMS only through `ctf.bridges`; CTF
never imports CMS or Engine models. CMS owns the public participant/range
control facade and revalidates the current target, workspace, lifecycle, and
capability. Engine owns operation generation, durable launch, input/result
persistence, domain state, result application, and status events. The
provisioner and ADR-039 `gcp-gce` adapter alone touch the actual GCE guests.

Select the durable single-owner embedding posture P1 from
[RAES ADR-104](https://github.com/OpenRAE/rae/blob/ebb70a34b8e7d1cc8964c443841ae57e12ed1014/docs/decisions/adrs/adr-104-runtime-control-plane-architecture.md):
one immutable target/run binding per authoritative store and owner. CMS owns
installation, lifecycle and routing to that owner through the existing
`shared.raes` embedding boundary. Store lifetime and owner recovery are outside
the pausable range; pausing a guest must not remove control history. No second
portable runtime, shared multi-tenant store or concurrent worker ownership is
inferred. P0's ephemeral state is insufficient; P2's HTTP front end is not
required, and P3 distributed coordination is not claimed. A deployment unable
to provide the released durable-store/ownership contract cannot admit this
profile. This decision adds no listener or fictional provisioner Job service.

### Exact bindings and supervision

The closed installation policy binds one exact native lifecycle profile to
compiled participant/controller identities, immutable source and parameter
selection, run, episode, resource generation, complete dedicated footprint,
implementation/configuration digests and current organizational authority.
A product role or resource owner alone establishes no portable controller.

API-409 owns proposals, approval/denial, cancellation, policy validity and
accepted control history. Its trusted live-cut resolver establishes current
grants, scope, evidence and order. The linked action must retain its exact
proposal meaning and live approval. API-423 independently admits each control
and action crossing, and every participant-facing disclosure. Failed or stale
admission prevents native reservation or release; recorded approval alone
cannot authorize changed work. Only the released runtime folds portable state.

Native capability checks, complete resource bounds and strict audit conjoin at
their owning services. Installation limits bound history, active contexts,
request rates, callback deadlines and recovery work. They make no portable
modular causal-budget claim. API-424 pure provider resolution, shared state,
acyclic effect graphs and durable root budgets apply only to a separately
admitted modular installation. This profile installs none and schedules no
modular review/audit effect.

Pause and resume against the same native state must serialize. Each new action
revalidates the preceding observed postcondition, current authority and control
cut. Identical retries retain one action and operation identity; changed meaning
conflicts. A crash after reservation leaves work held until the runtime's
committed admission and current native authority are established. Uncertain
external invocation blocks repetition until readback supports a conclusion.

The CTF product decision retains only native approval, actor, authority, fence
and correlation references. CMS owns the durable product-to-compiled binding
and owner routing. The released RAES store owns portable control and crossing
history; Engine owns native reservation, input, execution and results.
No workflow state belongs in communication, audit, task or range-config JSON.
Conformance verdicts come from the exact released checker. Native service and
provider evidence remain additional independent acceptance obligations.

The current CTF range-lifecycle API uses `EventCapability.RANGES`, then its
service rechecks `event.manage_ranges` and passes the initiating
`CredentialContext` and exact event target through CMS to Engine. Preserve that
path; do not reintroduce the historical `participant.user` substitution. The
control boundary carries the approving principal, initiating credential/policy
authority and target owner as separate facts, preserves the existing direct
CMS authorization path, and must strict-audit the actual approval
decision before the launch intent can be claimed. Authorization, approval,
execution admission, and audit evidence remain distinct records and outcomes.
`admin_external_audit` supplies the correct intent-before-effect shape only for
platform-admin overrides; its owner/staff no-op behavior is not the approval
provider required by this profile. Every admitted authority source needs the
same strict decision evidence, while the existing platform-admin override audit
remains intact.

Approval is a deliberate durable decision on the exact proposal digest, action,
target scope, policy/configuration revision and finite validity interval.
Denial and expiry remain explicit. The same currently qualified organizer may
request and explicitly confirm a proposal; version 1 does not claim two-person
approval or resistance to approver error. A changed proposal, target, authority
or configuration requires new approval. Recording approval does not execute,
endorse data or enlarge authority; dispatch requires fresh resolution and all
native gates. A scenario, service principal or participant cannot self-approve
through content. Approval request visibility is separately sink-admitted.

The current CTF/CMS/Engine lifecycle facade returns a product response or
boolean/task acceptance rather than the newly reserved `operation_id`, and its
already-paused/already-ready path may create no operation at all. Claimable
control evidence must instead bind the decision to the exact Engine generation
that actually executed, or explicitly record an occurrence-specific no-op
against authoritative current state. It must never recover correlation by
querying the latest range operation, treating the cached CTF status as
readback, or treating a task identifier as an operation generation. Pause and
resume continue to use the canonical `resource=range` operation transport; a
second RAES-specific pause/resume command or payload is not introduced.

Authorization is not an indefinitely reusable snapshot. Native approval and its
strict audit precede the RAES expected-head commit of control state/budget/intent.
The product decision and exact Engine operation reservation/binding then commit
before the launch intent is claimable. These are separate durable boundaries:
there is no two-phase commit or atomicity claim across the RAES store, Django
database and GCE. Recovery reconciles exact references across crash gaps.

The PC-11 logical effect key is the admitted run/root/rule-revision/effect-slot/
firing-epoch identity, not a state cut, retry number, HTTP request or task id.
It maps to one native Engine operation; same key with different content is a
conflict. Persist the relationship between the approved source generation and
the operation's legitimately advanced generation. Never use a latest-operation
query, reject the action's own reserved generation as stale, or create a new
operation because a response was lost. Resource incarnation, Engine operation
generation and RAES episode are distinct: a legitimate pause reservation does
not replace the world, whereas replacing the resource incarnation invalidates
its old admitted binding.

Event cancellation, participant removal, range replacement and authority
revocation suppress the exact pending operation through public services in the
same native transaction as invalidation. Extend Engine's existing locked
pre-Job gate; its destroy-specific provision-interrupt flow is not a generic
suppression primitive. Crucially, Job creation is not the final GCE invocation:
the admitted generation/authority/worker-ownership fence must also hold at each
actual cloud call. Neither task acceptance nor result-applier fencing proves it.
The provisioner consumes a closed native dispatch grant through the existing
operation boundary; it must not query CTF models or interpret portable approval.

Conflicting mutations/revocation cannot acknowledge a completed fence while an
older worker can still invoke. An expired worker lease or uncertain provider
call does not authorize blind takeover: prevent further effects until old
ownership and actual provider state are authoritatively reconciled. If the
adapter cannot enforce that boundary, the requested guarantee is unsupported.
After invocation begins, revocation is not rollback. Partial/failed/indeterminate
outcomes remain explicit, without a claim of instantaneous cancellation.

All native entry points affecting an actively controlled binding must enforce
these gates or refuse the operation; legacy endpoints cannot bypass the
profile. Unbound product lifecycle behavior remains separate. An emergency
out-of-world management action that breaks the admitted binding invalidates
the realization; it is not silently represented as a governed in-world effect.

Pause/resume is convergent but not atomic across a multi-VM world. Unsupported
asset mixes must be rejected before mutation by
`shared.range_lifecycle_capability`. Once provider I/O begins, a timeout or
member failure may leave a partial state. That outcome is `partial-failure` or
`timeout-unknown`, never success; it remains operator-visible and must be
observed/reconciled before retry. A later retry reuses the operation's
idempotency/generation rules rather than issuing blind compensating calls. The
current range worker collapses member failures to `cloud_operation_failed`;
that existing behavior is insufficient for the selected claim until #1968
preserves the ADR-039 partial/indeterminate distinction end to end. Its current
pause path also treats an NGFW-pause failure as non-fatal; that cannot satisfy a
whole-range postcondition that requires the participant access path to be
unavailable. The provider must either prove the exact selected postcondition or
reject that target/guarantee before mutation.

## Claim And Evidence Contract

| Proposed claim | Real implementation boundary | Authoritative readback | Failure behavior | Released RAES conformance | Explicit limitation |
| --- | --- | --- | --- | --- | --- |
| The local supervisory profile is supported | `shared.raes` released API-409/API-423 adapter plus server-owned native policy | exact compiled policy, implementation/configuration, action, resource and deployment identities | unsupported contract, native binding or requested guarantee rejects before mutation | released supervisory/crossing probes plus independently observed native outcomes | excludes generic API-424 modular-profile support and backend parity |
| The target has admitted participant resource scope | CTF event/participant service -> `ctf.bridges` -> CMS current range resolver and `shared.raes` binding | event, product participant, compiled RAES participant/controller/run/episode, package, resource scope, request/range and generation join | missing, non-dedicated, ambiguous, foreign, replaced or stale join rejects opaquely | portable identity/target fixtures plus Shifter authorization tests | no inferred agent selection, shared-resource control or union of participant policies |
| Capability restrictions constrain the parent | Current native policy and incumbent CMS/Engine gates | exact allowed action/resource binding and decision reference; denial proves no prohibited invocation | any unsatisfied authority or resource gate blocks the parent | API-423 refusal probes and native boundary-negative tests | not command filtering or confinement inside a guest |
| Proposal was explicitly reviewed | API-409 proposal -> CTF product supervision -> exact approval or denial | proposal/decision/validity references and strict audit | absent, stale or revoked approval cannot dispatch the parent | released API-409 validation, API-423 crossing probes and real service/UI evidence | approval and execution are separate; no automatic modular review or two-person claim |
| Resource work is bounded | Installation limits and Engine operation admission | exact footprint, one operation identity, bounded history and callback/recovery limits | exhaustion, stale generation or unavailable durable store prevents new work | released runtime checks plus native restart/replay/exhaustion tests | no modular causal-budget or model-spend claim |
| The effect was approved | explicit proposal-bound CTF product approval; separate current `EventCapability.RANGES` authorization; strict all-source `shared.audit` evidence | immutable approval/effect correlation, authority source, exact operation binding, and request-attributed audit | absent/mismatched approval, revoked/insufficient actor, invalidated event/participant, audit failure, or stale/replaced target prevents actual invocation | approval/audit protocol fixtures plus revocation, lifecycle-invalidation, pre-dispatch-race, and audit-failure tests | no autonomous scenario/range/controller approval; no approval inferred from authorization, content, or audit |
| Native pause was effected | CMS lifecycle -> Engine generation -> final invocation fence -> ADR-039 `gcp-gce` stop/readback | every admitted GCE member observed stopped, required access unavailable and Engine current generation applied `PAUSED` | unsupported rejects before mutation; partial/timeout stays failed or indeterminate and visible | #1968 contract tests; #1969 disposable real GCE proof | admitted persistent resources only; no RAM, frozen-world, destroy or quarantine claim; non-atomic across members |
| Resume was effected | same path using ADR-039 `gcp-gce` start/readback | every admitted member observed running/ready and Engine current generation applied `READY` | same fail-closed admission and truthful partial/timeout handling | #1968 contract tests; #1969 disposable real GCE proof | readiness is range lifecycle readiness, not arbitrary in-guest application health |
| Evidence is durable and auditable | released RAES authoritative runtime plus product decision refs, launch intent, immutable input, append-only result inbox, Engine applier, strict audit, and ADR-025 outbox | bounded audience-authorized projection joining RAES claim/history refs, product approval/authorization, operation disposition, current state, and audit correlation | dependency loss never invents approval or success; pending/failed/indeterminate remain distinct; retry preserves logical effect identity | released evidence/runtime contract plus replay, ordering, budget, redaction, sink-policy, and outage cases | no shadow runtime; no raw commands, rejected content, provider payloads, backend-private state, credentials, terminal streams, or general RAES observation claim |

No capability may be advertised merely because code, a row, a manifest key, or
a documentary mapping exists. #1969 real-provider evidence is required before a
released Shifter artifact claims the profile. A CTF communication being
delivered, a task being queued, a cloud API accepting a call, or one VM reaching
the target state proves less than the selected effect.

#1968 may exercise an installed candidate through an explicitly admitted
proof configuration without advertising released support. #1969 must bind
the actual implementation/configuration and installed RAES artifacts to the
observed results before capability publication. API-407 declarations, runtime
results, native readback, audit and released conformance must agree at that
same evidence scope; a provisioning-only sidecar cannot widen a manifest.

### Required cases for the selected claims

The terms in this table describe outcomes, not new Shifter wire enums.

| Case | Required observation |
| --- | --- |
| Deliberate teaching/session intervention | An authenticated proposal enters explicit supervision; exact current approval then permits the bound native pause/resume, with real GCE and access readback. Displaying a message or approving alone is insufficient. |
| Known in-world adversarial influence under permitted ordinary policy | The admitted test content can remain in the world while the resource-control decision follows its own constraints. This profile claims no IFC propagation, endorsement or adversarial detection. A requested SEM-233 enforcement profile remains independent and unsupported without its required instrumentation. |
| Denial, missing/failed mandatory result, or expired approval | Zero prohibited parent delivery/invocation; only independently authorized bounded rejection/review/audit evidence. |
| Changed proposal, profile/configuration digest, participant or generation | Old approval/permit cannot authorize the replacement; reject or resolve a fresh K with new approval where required. |
| Concurrent pause/resume or conflicting same-key content | No lexical winner, hidden restart or duplicate dispatch; explicit conflict or admitted ordered postcondition and revalidation. |
| Budget exhaustion, resolution loop or excessive member fan-out | Durable root limits block further effects; restart, replay, handoff or episode reset cannot replenish them. |
| Crash before RAES intent commit | No native dispatch; absent intent is not reconstructed as a completed effect. |
| Crash after intent commit, before/after native reservation or invocation | Reconcile the exact logical key and generation. Known absent execution can resume under fresh gates; uncertain execution requires readback and cannot be repeated blindly. |
| Revocation after Job creation but before a cloud call | Final invocation fencing prevents stale execution; launch/result fencing alone must fail this test. An uncertain old worker blocks takeover. |
| Partial member failure, cloud timeout or stale result | No whole-range success; retain observed per-member state, exact operation disposition and recoverable indeterminate evidence. |
| Foreign tenant/range/participant, unsupported asset or NGFW cascade | Opaque refusal with zero out-of-scope resource mutation; same-cell positive controls distinguish enforcement from general outage. |
| Audit, durable-store, provider or operation-integrity failure | No invented approval or success. Report failed/invalid realization and bounded native integrity evidence, not an in-world attack event. |
| Already stopped/running | Current authoritative readback plus occurrence-specific approval/correlation, without a fabricated provider execution. |
| Decision/reason/receipt at an unauthorized sink | No raw or hidden information escapes; failure, absence and timing follow admitted sink policy, independently of the parent. |

## Cross-Cutting Layers And Canonical Incumbents

| Layer | Required gate/reuse |
| --- | --- |
| HTTP authentication | Reuse bearer-first `ApiTokenAuthentication` and session authentication. A malformed bearer token fails closed and never falls through to a session; session mutations retain CSRF. |
| Token scope | Reuse the exact existing `ctf:event:write` scope for the organizer range-management audience. Do not add a broad `raes:*` or wildcard scope. A future external controller is a new audience and is unsupported here. |
| Identity, scope and CTF authorization | Reuse `shared.credentials.CredentialContext`, `shared.identity_scope`, `ctf.services.authorization.assert_event_action`/`admit_event_actions` and `ctf.services.unified_authorization` for exact `event.manage_ranges` (`EventCapability.RANGES` at the API). Re-resolve credentials and SQL ancestry through the owning services, then use the configured shared authorization provider and credential ceiling. Policy failure is unavailable/deny, never a fallback to local owner/staff/admin rules. Keep remote policy evaluation outside database locks and recheck local admitted bindings under the existing locks. An API-view check, membership, creator, range owner, UI visibility, approval row or audit evidence supplies no durable authority. |
| Approval and invocation freshness | Wire invalidation into event cancellation, participant removal, range replacement and authority changes through existing public services. Commit native decision/operation correlation before claimability; extend the locked launcher gate and enforce the admitted generation/authority/ownership fence at each actual cloud call as specified above. Communication hooks and destroy-specific provision interruption do not establish this control fence; no direct provisioner access to CTF models. |
| Target authorization | Re-resolve the event-qualified participant and current dedicated range; reuse CMS `_unified_authorization.require_range_action`, `_scoped_range_lifecycle` and Engine's prepared lifecycle/authority services. Require exact account/organization/workspace ancestry where present, event parent, resource incarnation and owner agreement across CTF/CMS/Engine; absent subdivisions do not mean installation authority. Bind released controller/episode/run/world identities to the admitted package, parameterized run identity, compiled plan and current range generation. Keep target owner separate from approving actor and preserve opaque foreign-target refusals. |
| RAES validation/runtime | Only `shared.raes` loads the released portable DTO, validates exact profile/mechanism/provider/configuration identities, versions, digests, package/occurrence/context/history-cut binding, invokes released supervisory/crossing validation and applicable conformance, and commits through the released authoritative runtime. All selected authority and crossing gates must hold at the current cut. A separately installed modular mechanism additionally follows its own required-slot and effect rules. No raw SDL reparse, app-local portable serializer, local composer/verdict, or sidecar runtime. |
| API/request shape | Reuse `shared.api.strict_json.ClosedJSONParser` for bounded JSON objects and duplicate-member rejection, and `shared.api.closed_serializer.ClosedSerializer` for unknown-field rejection plus explicit field bounds/types. The caller identifies the already-bound intervention/participant occurrence; the server derives target, provider, operation and profile. Reuse `shared.raes.json_ingress.parse_bounded_json_object` for portable JSON ingress inside its owning boundary. Do not copy parser/serializer logic or accept alternate parsers that bypass the closed JSON contract. |
| Capability/provider admission | Join the CTF participant/event to the current CMS `RangeInstance`; require its server-derived CTF source/workspace/scenario and validated RAES package source/digest; then reuse persisted Engine `Range.range_backend` and instantiation purpose, `shared.range_lifecycle_capability`, current `ResourceStatus`, and current operation generation. Never re-read an environment selector or infer RAES/control support from a scenario-id string, cloud/provider name, or range ownership alone. |
| Persistence/wire shape | Keep only product authorization/approval/fence/correlation references in the narrow CTF-owned control decision. RAES owns portable history, provider-state transitions, budgets, effect claims and dispositions. Reuse `ProvisionerLaunchIntent`, immutable `OperationInput`, `shared.operation_envelope` (authority-bearing v2), `shared.operation_authority`, `shared.operation_results`/`operation_result_payloads`, and append-only `OperationResultInbox`. Extend only the bounded native operation-specific projection needed for an admitted dispatch grant; never carry portable control workflow JSON. Preserve exact keys, bounds, digest conflict detection, step ordering, ownership and generation fences. RAES's published canonical control digest and native `canonical_payload_digest` have different contracts; use each for its own artifact, never interchange or rewrite retained digests. |
| Provider/config | Reuse ADR-039 `gcp-gce`, `load_gce_range_cell_config`, `gce_range_cell_power`, persisted backend/purpose/placement, least-privilege workload identity, private range networking, existing deadlines and exact deployed artifact identity. Before calling the power helper, join every target project/zone/instance and native UUID to the trusted complete generation-bound footprint; accepting its metadata shape alone proves neither ownership nor scope. Require nonempty membership; the shared capability helper accepts an empty set and the legacy query sees only ready/paused members. Include dedicated access resources; do not silently omit failed/missing members. Bind control-provider/configuration identity/digest separately from provisioning-only `SHIFTER_REALIZER_CONFIGURATION`. No request/scenario/handler-local environment selector or arbitrary endpoint is admitted. |
| Secret handling | Control records carry admitted identifiers/digests only. Reuse authentication stores, workload identity/provider secret stores and `shared.cloud.sensitive_env.split_env` plus Kubernetes `_secrets` for existing Secret-backed Job values. The classifier recognizes names, not secret content; a `_URL`, `_PATH` or `_REF` suffix does not make embedded credentials safe. Do not add credentials, raw participant content or provider-private state to control-record JSON, portable evidence, audit detail, events, metrics labels, fixtures, task payloads or environment dumps. |
| OS/process exposure | Preserve canonical structured argv: resource/operation plus request and operation UUIDs only, using canonical `resource=range`; the provisioner CLI has no `raes-range pause/resume` implementation. Preserve the GCP validating-admission policy's fail-closed launcher/service-account/image/argument/env/volume/hardening checks, dedicated launcher RBAC and network policy, no service-account-token mount, non-root/read-only/drop-all/seccomp Job, and per-Job Secret delivery. Portable control payloads, actor data, profile documents, cloud identifiers, credentials, commands, scripts, and configuration blobs do not enter argv, shell strings, process titles, or workflow output. |
| Result validation | Reuse `provisioner_db_operation_input` discriminator/envelope checks, `shared.operation_results`, Engine `_operation_apply`/`_operation_apply_admission` and ADR-039 postcondition checks. New native projection/result shapes must agree at builder, persistence guard, independent consumer, closed reason/step registry and applier. A result changes domain state only after all digest/version/authority/ownership/generation/order/shape gates pass. GCE RUNNING alone does not prove guest health or restored remote access; resume must also meet the existing readiness/access contract. |
| Audit/observability and sinks | Reuse `shared.audit.request_audit`/`principal_actor_fields` and `audit_log(..., strict=True)`: record permitted, denied and triggered decisions before consequential service work or participant delivery for every authority source, and retain strict Engine outcome audit. Commit failure prevents dispatch. Apply released sink/audience policy independently to decisions, reasons, approvals, receipts and evidence. Use stable codes, bounded counts/timings and admitted identifiers through `shared.log_sanitize`/provisioner `log_redact`; sanitizing/truncating text does not remove secrets. Do not log raw provider exceptions/traceback content or use per-participant/effect IDs as unbounded metric labels. Keep durable audit references for correlation; process-local log fingerprints are not portable identities. |
| Error envelopes | Portable failures become bounded diagnostics inside `shared.raes`; services reuse CTF/`CMSError`/shared validation errors and distinguish denied, unsupported, conflict and unavailable outcomes. Reuse `shared.errors` and `shared.api.errors` for authored public text and the existing request-id envelope. Declare the owning serializer for allowed validation-detail keys; neither `str(exc)`, attacker-supplied keys, chained causes nor provider/database/RAES diagnostics become public details. No new error wrapper or exception hierarchy. |
| Events/read models | Reuse ADR-025 outbox and reconciliation for product status projection. WebSocket/notification delivery is advisory and never control readback or success evidence. |
| Cross-layer imports | Preserve ADR-001, `.importlinter`, and `scripts/check_layer_imports/layer_imports.yaml`: CTF -> `ctf.bridges` -> public `cms.services` -> public `engine.services`; only `shared.raes` imports `raes_*`. |

Implementation must admit finite budget/approval limits, exact provider
configuration and durable-owner/storage policy before enabling this profile.
These are installation-owned, not scenario-owned choices. Any new typed setting
and closed validator must pass through `config/settings.py`,
`config/env-manifest.json`, `installation/schema.py`, `installation/registry.py`,
the runtime inventories, provider renderers, deployment overlays, and parity
tests. On GCP this includes the closed `installation/settings_gcp.py` and
`settings_gcp_deploy.py` models, `scripts/gcp/render_runtime_env.py`,
`engine.ecs._env`, `shared.cloud.gcp.task_runner`, the neutral Kubernetes
profile/Secret builders and Helm's `validatingadmissionpolicy-provisioner-jobs`:
env keys, required bindings, literal/Secret classification and rendered values
must agree, including native Cloud SQL auth. Use `config._product_env.product_env`
for established product settings; do not bypass the installation backend's
closed setting registry. This design adds no executable configuration.
A handler-local `os.environ` read, free-form JSON profile,
scenario-selected module, or provider-specific UI branch is forbidden.

## Extensibility Seams

For initial supervision, the closed native action table binds the released
API-409/API-423 path to the admitted participant, controller and complete native
footprint. The modular profile table described below is a future extension seam;
it is not required to enable this path. Neither table loads executable code.

The required seam is a closed server-owned profile table keyed by the exact
portable profile/mechanism/effect/provider/configuration identities, versions,
and canonical digests plus verified operating mode and persisted range
provenance/purpose/backend adapter. Those verified bindings and the exact
context/history-cut reference are the stable resolution parameters; the
selected local profile name/version/digest is an output, never caller input. A
profile maps to a fixed composition of approval provider, authorization
provider, effect dependencies and set, effect provider, readback policy,
audience/sink policy, and evidence policy. It is data/policy over existing
service seams, not a plugin loader and not caller-selected code.

The next provider variation is another ADR-039 adapter realizing the same
persistent-resource pause/resume postconditions. It can join only with its own exact
profile/provider identity and real conformance evidence; adding it does not edit
CTF workflows or weaken GCE evidence. The initial profile already requires a
server-derived RAES participant selection persisted with ownership context.
Until then, Mission Control/multi-participant cases fail rather than unioning
policies. Dynamic IFC, runtime shielding, capability restriction inside guests,
controller handoff, and live-environment control each require a distinct
mechanism profile, trust model, provider, failure contract, readback, and
conformance evidence; none extends this profile by adding an enum member.

## Gotchas And Anti-Patterns

- A participant-control controller is not an AD domain controller, organizer,
  Django actor or access account. Engine lifecycle terminology and a
  non-persisted `RunDescriptor` do not supply an active RAES episode/history cut.
- Do not put portable DTOs, workflow history, provider state or budgets in
  `RaesParticipantRuntimeRecord`, `RaesOperationRecord`,
  `CommunicationIntent` JSON, `range_config`, task metadata or audit JSON.
- Do not add a shadow runtime, executor, queue, event bus, outbox, audit table,
  evidence repository, provider plugin registry, config parser, error envelope
  or exception hierarchy. The narrow CTF product record does not duplicate
  RAES or Engine authority.
- Reuse the existing closed serializer and JSON parser together; a default DRF
  serializer supplies neither unknown-field nor duplicate-member rejection.
- Keep native `resource=range` pause/resume dispatch, exact operation
  correlation, all-source audit and existing authentication/CSRF/scope rules.
  Task identifiers, cached status and a latest-operation lookup are not proof.
- Do not reuse CTF's immediate asynchronous restart sequence, Engine's
  destroy-specific provision interruption, or the non-fatal NGFW cascade as
  the selected control/fencing/postcondition contract.
- Do not infer a current provider observation from an idempotent no-op.
  Correlate the occurrence and read back current state without inventing a call.
- Audit, evidence, approval and receipt visibility are independently admitted
  sinks. Their existence, reason and timing are not automatically public.
- Do not turn platform compromise/protection into an in-world occurrence or
  promote provisioning evidence into a control, IFC, shielding or parity claim.

## Non-Goals And Implementation Gates

- No mechanism implementation, API, model, migration, worker, provider call,
  manifest change, package upgrade, or conformance assertion in #1967.
- No generic plugin manager, second RAES runtime, Shifter-authored portable
  participant-control schema, simulation backend, external controller, or
  controller-handoff protocol.
- No individual in-guest process/action control, dynamic IFC, runtime shielding,
  network reconfiguration, destroy/rebuild, resource resize, command execution,
  or arbitrary intervention.
- No expansion to AWS, GDC, non-CTF/Mission Control, federated, or genuinely live
  environments, and no change to product naming.
- No replacement of CTF authority, CMS/Engine range lifecycle, ADR-039,
  ADR-043, shared audit, provider secret stores, ADR-025 events, terminal access,
  or Guacamole.

The current repository pins RAES 10.6.0 and environment packs 7.2.2. The former
upstream blockers are closed; do not reopen the historical release dependency.
The remaining admission gate is the exact compatible released contract/protocol,
runtime and probe subset for this profile, consumed through `shared.raes` and
matched to actual service/provider behavior. A git revision, copied DTO, local
verdict, UID list or `DRAFT` requirement is not implementation evidence.

GEN-2005 is the cross-cutting Ground Control constraint for this decision and is
currently `ACTIVE` because implementation has started. Its native power
preflight and readback links cover part of this constraint. They do not claim an
implemented participant-control runtime or conformance.

The accepted upstream #1068 design supplies #1967's portable authority. The
closed implementation children in OpenRAE/rae are
[#1070](https://github.com/OpenRAE/rae/issues/1070) (semantics),
[#1072](https://github.com/OpenRAE/rae/issues/1072) (contracts),
[#1069](https://github.com/OpenRAE/rae/issues/1069) (runtime), and
[#1071](https://github.com/OpenRAE/rae/issues/1071) (conformance).
Record the consumed release and exact contract/fixture identities with the
implementation; accepted design commits alone do not suffice. #1968 itself
must include at least one real participant/world crossing through authenticated
Shifter services. #1969 extends that evidence; it cannot defer #1968's first
end-to-end acceptance criterion.

GEN-2005 records partial IMPLEMENTS/TESTS links for the native power boundary.
Remaining clauses still require implementation and proof. #1967 retains DOCUMENTS links and
makes no such runtime claim. Support advertisement additionally requires #1969
real-boundary proof. Neither LilRAE implementation nor its evaluation issues
are a prerequisite or evidence of Shifter support.

Core profile implementation/proof does not depend on CTF communications
#2050/#2054: those integrations depend on this core, and reversing the order
would create a cycle. ADR-051 provenance remains relevant when a communication
later invokes an already admitted typed control mapping; communication delivery
is not the control mechanism or its proof.

## Validation

This architecture-only change must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Existing ADR registry, guardrail-documentation and import checks protect
repository structure; they do not enforce or prove the proposed runtime
guarantees. This documentation-only delivery uses the user-approved design
review and existing document checks, without a new executable policy contract.
Implementation remains subject to the stack-native checks and behavioral tests
in `AGENTS.md`; #1969 supplies the disposable real-provider
control/readback/isolation evidence. Mandatory audit is distinct from optional
experimental capture, retention or export.

Reuse the existing `tests/shared/raes` publication/conformance gates,
`tests/engine/services/test_prepared_launch_commit_fences.py`, native launch
outbox/inbox tests, organizer authority/audit tests, provisioner
`test_gce_range_cell_power.py` and installation/runtime-env/Job-policy parity
tests. The required negative cases above must assert absence of forbidden
provider calls and participant delivery, not just HTTP error codes; include
revocation after queueing, stale/conflicting cuts, crash/reopen/replay, exhausted
budgets, audit failure, partial members and deceptive provider/error payloads.
Use targeted local tests and pragmatic mutation checks for these gates, with
full suites in CI. Synthetic fixtures remain in this repository; private pack
content and operational acceptance evidence stay in their owning repository.
