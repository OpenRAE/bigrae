---
id: PLAT-202
title: "Per-Range LLM Access Management"
status: DEPRECATED
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-04-16T22:49:32.549002Z
updated_at: 2026-11-11T00:00:00Z
---

# PLAT-202: Per-Range LLM Access Management

## Statement

Historical requirement, retired on 2026-11-11. Issue #2909 removed the model broker and its model-access control subsystem (ADR-068). Keyless direct access (ADR-064) is the only guest model path.

The platform shall provision per-range access to external LLM and agentic-tool APIs, with shardable allocation across models, clouds, and accounts. Shard assignment, credential plumbing, and endpoint routing shall be a first-class platform capability rather than an out-of-band operator script. Shard strategy shall be configurable per scenario or per event, informed by event capacity declarations (CTF-908) and planned by capacity-aware provisioning (PLAT-201).

Tenant administrators shall manage source configurations and write-only provider credentials from the tenant UI. Authorized scenario users, existing-range administrators and CTF organizers shall select or mix approved sources with explicit weights while preserving source-use authority, shared and per-range limits, immutable prices and outstanding accounting. Source placement shall be independent of compute hosting: the platform's own GCP project is permitted alongside external projects, accounts and providers. Source changes shall compare revisions, fence old grants and retain liabilities without automatically replaying potentially billed requests.

## Rationale

Scenario authors need a provider-neutral way to request model access. The platform owns allocation, policy, accounting and revocation through the model broker; executable adapters consume scoped guest enrollment without receiving provider credentials.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#681` (PLAT-202: Per-Range LLM Access Management)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2118` (Policy catalog and shared access contracts)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2139` (Persist sharing bindings and resolve overlapping policies)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2140` (Project sharing membership and fence authority changes)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/architecture.md`
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/canonical-json-v1-vector.json`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2123` (M06 disabled GCP broker deployment package)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/gcp-packaging.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2119` (M02: enforcing scenario/event model admission)
- IMPLEMENTS → DOCUMENTATION `docs/adr/060-model-access-allocation-accounting.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2120` (M03: durable quota allocations and non-usable pending grants)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/allocations.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2121` (M04: atomic request budgets and dispatch leases)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/request-accounting-preflight-2121.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2243` (Tenant model sources across scenario, range and event flows)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/source-management.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2122` (M05: bounded private broker and authenticated control API)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/broker-runtime.md`
- DOCUMENTS → DOCUMENTATION `docs/architecture/model-access/broker-preflight-2122.md`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2126` (M09: scoped operator and organizer model-access management)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/management-preflight-2126.md`
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2124` (M07: Vertex invocation and usage adapter)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/vertex-adapter-preflight-2124.md`
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/bigrae#2411` (Optional model-access controls through a gateway, ADR-068)
