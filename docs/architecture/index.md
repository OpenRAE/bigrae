# Architecture records

Read the [current-state architecture handbook](../technical/architecture.md)
for the runtime, ownership and support model. It is published through the
single MkDocs site and linked from the root README.

This directory contains explanations of designs and references to implementation evidence.
Preflights record constraints at an issue's review baseline.
Their status notes apply at direct links as well as through this index.
They do not prove implementation, activation, support, or live qualification.
Original evidence and paths remain available for traceability.

Accepted ADRs and durable designs also live here.
They retain their stated authority until amended or superseded.
An accepted ADR can retain constraints first recorded in a preflight.
The filename alone does not determine a decision's authority.
Read the [decision guide](../adr/README.md), source code, and current handbook together.

## Choose a record

| Reader question | Route and applicability |
| --- | --- |
| How does the current system work? | [Current architecture](../technical/architecture.md): maintained explanation with source and qualification limits |
| Which design boundary applies? | [External runtime design](external-scenario-runtime-design.md): durable explanation; runtime support still needs evidence |
| Which decision is accepted? | [ADR-070](../adr/070-github-less-gcp-deployment.md): release-based GCP deployment decision |
| Which decision was superseded? | [ADR-067](../adr/067-model-access-enforcement-optional.md) links its replacement, [ADR-068](../adr/068-model-access-broker-parked.md) |
| What is required? | [Requirement reference](../requirements/README.md): normative statements and traceability; `ACTIVE` does not mean delivered |
| What did an audit find? | [Audit reference](../audit/README.md) and [REV1 review](rev1/README.md): dated findings with baseline limits |
| What did the research suggest? | [Research reference](../research/README.md) and [CTF studies](../ctf/README.md): results, recommendations, and estimates |
| Where are visual examples explained? | [Design explanations](../design/README.md), including maintained HTML/CSS artifact descriptions |
| How should old instructions be read? | [Internal notes](../technical/notes/README.md), [plans](../technical/plans/README.md), and [deprecated documentation](../_deprecated/README.md) |

## Find implementation history

Use the issue number or subject to locate a record without treating it as
installation guidance:

```shell
rg --files docs/architecture | rg 'preflight|review'
```

REV1 and later adoption reviews are dated assessments. Their evidence limits and
superseding decisions matter. Do not infer a live release claim from a proposed
control or an earlier passing test. This directory remains excluded from the
public MkDocs site; exclusion is not a confidentiality boundary.

## Durable design notes

These retain their stated design authority and are not historical preflights:

- [Artifact preparation](raes-in-tenant-artifact-preparation-design-1583.md)
- [RAES hard cut](raes-migration-adr.md)
- [RAES 10.6 contract-pair adoption boundary](raes-contract-pair-adoption-2722.md)
- [Tenant trial archive intake boundary](experiments-trial-archive-intake-boundary-2740.md)
- [Disposable trial worker boundary](disposable-trial-workers-boundary-2741.md)
- [Pack experiment admission boundary](experiment-admission-boundary-2742.md)
- [Admitted trials on disposable workers](parallel-trial-dispatch-boundary-2743.md)
- [Trial archive custody design](trial-archive-custody.md)
- [Retained experiment result exports](experiment-result-exports.md)
- [External runtime boundary](external-scenario-runtime-design.md)
- [Named file assets and adapter inputs](named-file-assets-2719.md)
- [Adapter values before provisioning](adapter-pre-provisioning-2718.md)
- [Registered GCP range projects](registered-gcp-range-projects-2716.md)
- [Temporary participant range access](temporary-participant-range-access-2785.md)

- [Shared deployment configuration](deployment-root-consolidation-2089.md)
- [Verification and adoption ownership](verification-adoption-ownership-design-2090.md)
- [Browser CSP enforcement](browser-csp-enforcement-design-2090.md)
- [GCS CMEK](gcp-gcs-cmek-design-2564.md)

- [Team captain controls (#646)](ctf-team-captain-preflight-646.md)

- [Pack experiment admission design](experiment-admission-design-2742.md): retained inputs, security boundaries, and claim persistence.
- [Shared documentation tool boundary (#2804)](documentation-tool-adoption-2804.md)
- [User documentation boundary (#2805)](user-documentation-boundary-2805.md)
- [User guide reader routes and data flows](user-guide-entry-paths-2805.md)
- [Architecture and historical documentation boundary (#2808)](architecture-history-documentation-2808.md)
- [Parallel trial dispatch design](parallel-trial-dispatch-design-2743.md): worker trials, native operations, data flow, and controls.

- [Interface documentation boundary (#2807)](interface-documentation-design-2807.md)
