---
id: GEN-2005
title: "Participant-control realization and integrity"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 2
created_at: 2026-09-06T00:00:00Z
updated_at: 2026-11-04T00:00:00Z
---

# GEN-2005: Participant-control realization and integrity

## Statement

When Shifter admits a RAES participant-control profile, it MUST satisfy all of
the following obligations:

1. Consume the exact released RAES semantics, provider protocol, runtime and
   conformance contracts through `shared.raes`. Bind profile, mechanism,
   provider implementation and configuration identities and digests explicitly.
   Scenario or participant content MUST NOT select executable code. Shifter
   MUST NOT duplicate portable DTOs, control semantics or conformance verdicts.
2. Resolve the admitted participant, controller, episode, run, declared world,
   authority and current range generation from trusted product and compiled
   scenario bindings. Keep platform, tenant, credential, service and isolation
   integrity outside that world. An integrity failure invalidates or fails the
   realization; it MUST NOT be relabeled as an in-world adversarial occurrence.
3. Use API-409 for explicit supervisory decisions and API-423 for governed
   participant crossings. Native permissions, resource limits and strict audit
   remain organizational service obligations. Explicit approval does not require
   an API-424 scheduled review effect. If modular mechanisms are separately
   selected, compose them through the released RAES rules at the same
   exact context and history cut. Mandatory missing, stale, unknown,
   unsupported, failed, weakened, abstaining or conflicting results MUST NOT
   authorize an effect. Preserve distinct approval, authorization and execution
   decisions, explicit effect dependencies and durable finite causal budgets.
4. Mediate every admitted consequential action through the owning authenticated
   and authorized service and backend path. Bind any required explicit approval
   to the exact proposal and current authority. Fence actual invocation against
   stale generation, authority and ownership; task acceptance or a result-applier
   fence alone MUST NOT establish this guarantee. Reject unsupported targets or
   guarantee strengths before any prohibited world or backend effect.
5. Commit control history, provider-state transitions, causal budgets and effect
   claims through the released authoritative runtime. Correlate native approval,
   Engine operations, audit and readback without creating a shadow runtime or
   duplicating execution truth. Retry and replay MUST preserve logical effect
   identity. Partial and indeterminate outcomes require readback before a retry
   that could repeat an effect; interruption or revocation MUST NOT imply rollback.
6. Apply audience and sink policy to decisions, reasons, approvals, receipts and
   audit evidence as well as participant content. Preserve bounded, digest-bound
   references and limitations without exposing credentials, raw rejected content
   or backend-private state through portable records, logs, events or errors.
7. Advertise support only for the exact installed and admitted mechanism,
   profile, provider, configuration, participant/world and deployment envelope
   supported by released RAES conformance and real service/provider readback.
   Manifest presence, unit tests or another backend's results MUST NOT substitute
   for realization evidence or imply mechanism, guarantee or fidelity parity.

## Rationale

Portable RAES authority does not select a Shifter mechanism or establish its
organizational authority, resource coverage or platform integrity. Shifter needs
an independently selected, measurable realization contract that composes with
its existing CTF, CMS, Engine, audit and deployment ownership boundaries.

ADR-058 specifies the initial design. Implementation has started under #1968,
so this requirement is ACTIVE. The native GCE boundary now checks the complete
power footprint before mutation, rechecks instance identity and disk attachments,
and retains observed member outcomes on partial failure. These are native
safeguards, not a delivered participant-control profile. Released supervisory and crossing integration,
authenticated participant/world crossing, durable control ownership, and
real-boundary proof remain required. ACTIVE does not mean delivered or conformant.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `1967` (Participant-control mechanism and realization design)
- DOCUMENTS → GITHUB_ISSUE `1968` (Selected mechanism implementation tracking)
- DOCUMENTS → GITHUB_ISSUE `1969` (Real-boundary proof tracking)
- DOCUMENTS → ADR `docs/adr/index.yaml` (ADR-058)
- DOCUMENTS → DOCUMENTATION `docs/architecture/raes-participant-control-realization-envelope-1967.md` (Selected realization envelope and claim/evidence contract)
- DOCUMENTS → SPEC `https://github.com/OpenRAE/rae/blob/ebb70a34b8e7d1cc8964c443841ae57e12ed1014/docs/research/modular-participant-control/composition.md` (Accepted portable PC-01 through PC-15 authority)

- DOCUMENTS → DOCUMENTATION `docs/architecture/raes-participant-control-adoption-1968.md` (Current implementation design and claim limits)
- IMPLEMENTS → CODE `shifter/engine/provisioner/gce_range_cell_power.py` (Partial: observed persistent power footprint and incarnation readback; no portable mechanism claim)
- IMPLEMENTS → CODE `shifter/engine/provisioner/range_ops/_pause_resume.py` (Partial: whole-range preflight, bounded failures, and observed member outcomes)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_compiled_participants.py` (Partial: encrypted generation/custody-bound compiler input, immutable replay and reference-only projection)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/power_input.py` (Partial: complete compiled footprint and retained native addressing; no execution authority)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_operation_apply_native_power.py` (Partial: exact-operation member readback, strict audit and complete terminal settlement)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_participant_actions.py` (Partial: installed API-409 proposal/approval linkage and exact native action commitment; no modular-profile or native-effect claim)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_power.py` (Partial: current native authority, full-footprint reservation, immutable input, strict audit and dispatch hold)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_dispatch.py` (Partial: exact committed admission releases held native work once, under current authority and strict audit)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_invocation.py` (Partial: live workload authentication and one-use member permission; runtime transport and settlement remain required)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_input.py` (Partial: authorized current compiler input and complete native footprint for controller installation)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_power_candidate.py` (Partial: fixed logical control mappings, prospective planning refusal and separately qualified native target)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_supervision_cursor.py` (Partial: request coordinates from the released owning v2 fold; no native authority grant)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_power_planning.py` (Partial: selected source planning retains native artifact gates and exact compiler context; product installation remains required)
- IMPLEMENTS → CODE `shifter/engine/provisioner/native_power_invocation.py` (Partial: exact grant comparison immediately before the fixed bounded provider call; uncertain completion retains exclusion)
- TESTS → TEST `shifter/engine/provisioner/tests/test_gce_range_cell_power.py` (Native footprint and readback refusals)
- TESTS → TEST `shifter/engine/provisioner/tests/test_range_pause_resume_dispatch.py` (No mutation on failed preflight, partial outcomes, and private diagnostics)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_compiled_participant_binding.py` (At-rest encryption, private projection, unchanged replay and stale custody)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_power_results.py` (Complete and partial readback, incarnation/target/input fencing and atomic audit failure)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_participant_actions.py` (Released durable admission, exact approval meaning, refusal of optional unlinked paths and bounded private failures)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_reservation.py` (No dispatch before admission commit, current native authority and atomic audit failure)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_admission.py` (Released durable runtime through actual Engine authorization, audit and held reservation; revoked authority prevents native work)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_dispatch.py` (Current committed admission, exact release retry and audit rollback)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_invocation.py` (Live workload, concurrent acquisition, generation exclusion and atomic invocation audit)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_runtime_input.py` (Stale, unauthorized or unsupported controller installation input is withheld before private decryption)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_power_candidate.py` (Public planning, governed admission and unresolved-evidence refusal through a separately assembled target)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_supervision_cursor.py` (Released fold handles accepted and rejected history positions and refuses altered context)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_power_package.py` (No implicit activation, no invalid-selection fallback, artifact admission and private compiler retention)
- TESTS → TEST `shifter/engine/provisioner/tests/test_native_power_invocation.py` (Exact grant, lost replies and per-call cessation through the actual GCE power helper with synthetic clients)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_kubernetes_workload_identity.py` (Explicit-audience TokenReview and live Pod/Job identity; private API failures remain bounded)

- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_control_plane.py` (Partial: released durable supervisory and crossing composition, explicit final-sink selection and owner cleanup)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_participant_crossings.py` (Released current/denied/revoked crossings and required-flow refusal before native reservation; synthetic policy inputs)
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/models/participant_control.py` (Partial: immutable organization configuration and native product/run correlation; no portable history)
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_participant_control_binding.py` (Partial: exact product, source, compiler and generation admission through native owning services)
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/services/range/participant_control.py` (Partial: current event policy and actual participant assignment fence)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_supervisory_requests.py` (Partial: original bounded requests use released control declarations and exact owning-fold coordinates)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_cleanup.py` (Partial: strictly audited dispatch fencing and restoration only before provider-call permission)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_participant_control_configuration.py` (Scoped installation, immutable identity, irreversible retirement and audit rollback)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_participant_control_binding.py` (Real product/native custody, immutable source and changes during qualification)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_control_authority.py` (Current event permission, exact assignment and local proof revocation)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_supervisory_requests.py` (Prepared requests reach the released owner; stale cuts, denied actions and cancellation remain refused)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_cleanup.py` (No-permission retraction, unknown-call retention, replay refusal, native scope fences and atomic audit failure)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/artifact_planning.py` (Partial: exact original planner facts retained privately for recovery without new inventory admission)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_power_session.py` (Partial: persistent owner serialization, original request retry and exact native action read at its current cut)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/raes/native_power_authority.py` (Partial: fixed native authority and audience adapter through released supervisory and ingress contracts)
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_participant_control_authority.py` (Partial: current original requester, human reviewer and consuming proof with separate local fences)
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_participant_control_owner.py` (Partial: installed owner orchestration through native command audit, released admission, held release and one-use invocation; authenticated transport, fixed persistent deployment, and exact original request recovery)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_retained_artifact_planning.py` (Exact original artifact availability and mechanisms reopen without a current registry; missing and foreign facts fail closed)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_power_session.py` (Original episode recovery, exact request retry and unresolved invocation exclusion)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_power_authority.py` (Released crossings and native reservation enforce independently revoked original proofs)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_participant_control_authority.py` (Separate original proof admission and local commit fences)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_participant_control_owner.py` (Actual CMS/CTF/Engine custody, policy, released owner, held release, recovery and authenticated workload invocation with synthetic Kubernetes responses)

- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_participant_control_settlement.py` (Partial: durable command exclusion before late callbacks and failed admission cleanup)
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/api/participant_control.py` (Partial: authenticated binding, bounded read, original request submission and retry)
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/api/participant_control_internal.py` (Partial: private authenticated workload invocation protocol)
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_native_participant_recovery.py` (Partial: strict native fencing and read-only exact cloud cessation evidence)
- IMPLEMENTS → CODE `shifter/shifter_platform/frontend/src/features/ctf/admin/ParticipantControlCard.tsx` (Partial: human review, explicit effects, original retry and separate native status)
- IMPLEMENTS → CODE `platform/charts/shifter/templates/participant-control.yaml` (Partial: fixed persistent TLS owner, protected storage and limited workload verification permissions)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_control_api.py` (Authenticated released crossing, native release, immutable retries, privacy, scope and CSRF)
- TESTS → TEST `shifter/shifter_platform/tests/shared/raes/test_native_power_conformance.py` (Released carrier validation and official positive/negative fixtures; no overall conformance claim)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_native_participant_recovery.py` (Live worker exclusion, unknown history, exact cessation, strict audit and independent containment)
- TESTS → TEST `shifter/shifter_platform/tests/platform/test_admission_policy_apiserver.py` (Actual API server compilation and acceptance/refusal of pinned provisioner identity and runtime strings)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_power_pipeline.py` (One-generation authenticated review, actual outbox and standalone provisioner CLI, private TLS grants, synthetic Compute effect/readback, real SQL results, audit and released carrier verification; revoked permission produces no mutation)
