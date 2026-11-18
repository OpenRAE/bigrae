# User acceptance and qualification

This landing page routes operators and contributors to current protocols and retained records.
Live runs need authority for the target tenant and the workload.
Do not run them merely to verify documentation.

## Current how-to guides

- [QA protocols](../docs/qa/index.md): select the required behavior and evidence.
- [Range functional smoke](../docs/qa/range-functional-smoke.md): exercise an existing range without provisioning or destroying it.
- [Event capacity](../docs/ops/gcp-event-capacity.md): qualify the selected GCP shared-service profile.

## Harness reference and explanation

- [Range functional smoke implementation](range-functional-smoke/README.md): exact pass evidence, actor sources, safety, and targeted tests.
- [Event load harness](event-load-harness/README.md): traffic profiles, identity sources, metric adapters, and report limits.
- [Sample envelope report](event-load-harness/sample-envelope-report.md): illustrative values, not measured capacity evidence.

## Preserved records

- [Scenario editor test plan](SCENARIO_EDITOR_TEST_PLAN.md): historical SQL and validation proposal from 2026-02-21.
- [Scenario editor UAT plan](SCENARIO_EDITOR_UAT_PLAN.md): historical scenario-editor cases and execution-log template.
- `test.txt`: retained one-line test artifact with no current reader procedure or executable consumer.

The scenario-editor plans predate native pack ingestion and current authorization.
Their SQL, old endpoints, and role assumptions are not supported current procedures.
Do not execute their mutations against a current tenant.
Use [scenario authoring](../docs/dev/ctf-scenario-content.md) and [CMS contracts](../docs/technical/shifter_platform/cms.md) instead.
The original records remain exact below their new applicability notes.
