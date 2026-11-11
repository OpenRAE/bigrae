# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Purpose**: Reference template for a feature plan.
The retained `/speckit.plan` integration fills this template when that command is available.
No command definition is shipped at `.specify/templates/commands/plan.md`.
Use [the repository workflow](../../docs/DEVELOPMENT_WORKFLOW.md) and the installed implement skill for issue-driven delivery.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [for example, Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [for example, FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, for example, PostgreSQL, CoreData, files or N/A]

**Testing**: [for example, pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [for example, Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [single/web/mobile - determines source structure]

**Performance Goals**: [domain-specific, for example, 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, for example, <200 ms p95, <100 MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, for example, 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

[Current gates from AGENTS.md, accepted ADRs, and .ground-control.yaml. The retained constitution is historical reference.]

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (for example, apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [for example, fourth project] | [current need] | [why 3 projects insufficient] |
| [for example, Repository pattern] | [specific problem] | [why direct DB access insufficient] |
