# shifter-ops MCP security guardrails

This security reference describes the active tool policy and process boundaries.

The ops MCP server uses the local operator's AWS credentials. It can reach production-facing AWS APIs, the production database, and the operator's range infrastructure. **`shifter-ops` is an *operator agent surface*** under ADR-014-R5. Its client is the operator's trusted agent loop. Writes, mutations, SSM execution, and secret retrieval are intended operations within its policy controls.

The threat surface is therefore **not** "untrusted MCP client connects
to the server." It is:

1. **Prompt injection** of the agent through any text it reads
   (`get_log_events`, `filter_log_events`, `tail_logs`,
   `get_s3_object`, `ssm_get_command_output`, range guest stdout, web
   fetches, issue/PR bodies, teammate comments).
2. **Agent error**—hallucination, wrong instance id, dev/prod
   confusion, missing `WHERE` clause, retry storms.

Defenses bound the blast radius of any single call, not the
capabilities of the agent.

## Implementation status

This document describes the **target policy layer**, which has now
landed across issue #777 + sub-issues #1198–#1202. Today's runtime
status:

- `.shifter.yaml` exists at the repo root and `mcp/ops/policy.js`
  provides `parsePolicy`, `loadPolicy`, the `Policy` class, the
  `registerTool` wrapper, and the composed-gate wrap. Phase 1
  enforcement (class declaration and session-profile gating) is in
  place. Phase 2 (#1198) added five cheap-defense gates at the seam:
  env confirmation, dry-run defaults, description redaction,
  idempotency keys, secret-handle return-mode, and a per-call JSONL
  audit append via `mcp/ops/audit.js`.
- Phase 3 (#1199) wired the mid-cost gates: two-phase `plan_<name>` /
  `execute_<name>` registration for `infra_mutation`, `ssm_arbitrary`,
  and `db_arbitrary` tools; a 60-second TTL bounded plan store
  (size-capped at 64 entries); per-class sliding-window rate caps
  (`infra_mutation` default `{count: 3, window_seconds: 60}`); and
  startup `SHIFTER_OPS_PROFILE` resolution via `profileFromEnv` →
  `loadPolicy`.
- Phase 4 (#1200) wired the expensive gates: untrusted-input fencing
  (producer descriptors declare an `untrusted_source` label from the
  `.shifter.yaml` allowlist; consumer descriptors declare which
  free-form fields the wrapper must scan, refusing calls without
  `acknowledge_untrusted_input: true`); and apex out-of-band operator
  approval (configurable `apex_operations:` rules; single-use
  60-second hex tokens emitted to stderr; a dedicated `approve` MCP
  tool consumes them; headless / CI fails closed).
- Phase 5 (#1201) replaced every `server.tool(...)` registration in
  `mcp/ops/index.js` with a `registerTool(ctx, {...})` descriptor
  tagged by capability class. `.shifter.yaml` and
  `SHIFTER_OPS_PROFILE` are now load-bearing on the live server; the
  default `standard` profile excludes the destructive classes, so
  operators that need them must set
  `SHIFTER_OPS_PROFILE=destructive` at server startup.
- Phase 6 (#1202) added `mcp/ops/tool-surface.test.js`, the
  load-bearing ADR-014-R3 / R5 / R6 negative-surface suite referenced
  below. Tools register through an exported `registerAllOpsTools(ctx)`
  seam on `mcp/ops/index.js` so the surface tests can drive the live
  registration path (real `.shifter.yaml`, real `loadPolicy`, real
  `registerTool`) against a fake server without opening stdio.

The rest of this document describes the policy layer as it stands
today on the live server.

## Policy layer—target design (phased rollout)

The following sections distinguish implemented controls from design targets.
The phase numbers above retain delivery history; they do not prove live permissions or deployment qualification.
The current `.shifter.yaml` and owning policy modules determine the selected session's tools.

Every tool registered on this server is governed by a structured
per-tool policy declared in `.shifter.yaml` (`mcp_ops:` namespace at
the repo root). The policy assigns each tool exactly one **capability
class**:

| Class | What it covers |
|-------|----------------|
| `observability` | CloudWatch logs, `describe-*`, `list-*`—no writes, no secrets |
| `named_db_read` | Named, parameterized read-only DB diagnostics (for example range lookups) |
| `named_db_write` | Named, parameterized DB mutations |
| `secret_handle` | `get_secret`, `list_secrets`—returns references, not raw values |
| `ssm_named` | Allowlisted Django manage.py commands via SSM |
| `ssm_arbitrary` | Free-form SSM `send-command` / `get-command-invocation` |
| `db_arbitrary` | `query`, `execute`, `list_tables`, `describe_table` |
| `infra_mutation` | `start_ec2_instance`, `stop_ec2_instance`, `terminate_ec2_instance`, `restart_ecs_service`, `reconcile_ranges`, `build_ami`, `promote_ami`, `build_gce_image` |
| `dev_bypass_tunnel` | `start_portal_test_tunnel`, `stop_portal_test_tunnel` (agent auth without MFA in dev) |

Class membership drives the gates the policy wrapper composes around
each handler:

- **Session profile.** `SHIFTER_OPS_PROFILE=read_only | standard |
  destructive` selects which classes are registered as tools at server
  startup. Default `standard` excludes `ssm_arbitrary`, `db_arbitrary`,
  `infra_mutation`, and `dev_bypass_tunnel`. Operators opt into the
  `destructive` profile per session when they need those capabilities.
- **Environment policy.** No default to `prod`. Tools that touch prod
  require an explicit `confirm_env="prod"` argument; otherwise the
  call is refused before the handler runs.
- **Plan and execute.** `infra_mutation`, `ssm_arbitrary`, and `db_arbitrary` classes register `plan_<name>` and `execute_<name>` tools.
  The original direct tool is absent.
  Planning returns a summary and a short-lived plan ID without running the handler.
  Execution requires that single-use `plan_id` and runs the stored arguments through the execution gates.
  Apex operations also require out-of-band operator approval.
- **Secret handles.** `secret_handle` tools return an opaque handle
  (`shf-secret:<uuid>`) resolvable only inside the server process.
  Successful responses contain references instead of raw secret bytes.
  Internal helpers (`fetchCredentials` for the DB pool open) resolve the handle server-side.
  Error responses have the separate boundary described below.
- **Idempotency keys.** `named_db_write` mutations require an
  `idempotency_key` argument. Same key on retry returns the cached
  result, so an agent retry storm cannot compound.
- **Rate caps.** `infra_mutation` defaults to `{count: 3, window: 60 seconds}`
 —after three mutations in a minute, further calls are refused
  until the window resets.
- **Audit.** Every invocation appends a JSONL record to
  `~/.shifter-ops-audit.jsonl` (configurable): timestamp, tool,
  class, env, profile, sanitized arguments, result class, duration,
  plan id if any, idempotency key if any, error class if any.
- **Description redaction.** `dev_bypass_tunnel` tool descriptions
  are stripped of bypass procedures and URLs (per ADR-014-R6) before
  they reach `list_tools`. The capability is retained; the
  procedural text is not.
- **Untrusted-input fencing.** Tools that return text from untrusted
  sources (logs, S3 objects, SSM stdout, web fetches) wrap their
  output in `[UNTRUSTED:<source>:BEGIN] ... [UNTRUSTED:<source>:END]`
  fences. Free-form consumers include `query`, `execute`, `ssm_send_command`, and `run_manage_command`. They refuse fenced text unless `acknowledge_untrusted_input: true` is set. This forces acknowledgment before acting on untrusted source text.
- **Apex out-of-band confirmation.** A small set of apex operations
  (`terminate_ec2_instance` against prod, `execute_plan` for
  `db_arbitrary` writes against prod, `restart_ecs_service` against
  prod) require operator-terminal confirmation before executing: the
  server prints a token to stderr and pauses up to 60 seconds waiting for
  the operator to type it back via a dedicated `approve` tool. Fails
  closed on timeout.

The `.shifter.yaml` policy is the source of truth. The policy wrapper
fails closed if a tool is registered without a class, or if
`.shifter.yaml` is missing or malformed at startup.

## Database TLS

`mcp/ops` connects to the per-environment RDS Postgres database
through an SSM port forward (`localhost:<local_port>` → RDS endpoint
`:5432`). The pool is constructed by
`mcp/ops/lib.js::buildPoolConfig`, which is the single source of
truth for the TLS configuration.

**Trust model.**

- TLS verification stays on (`rejectUnauthorized: true`). Disabling
  verification—even as a documented exception—is rejected by
  ADR-014-R7 and by the `mcp-ops-tls-strict` adr_guard check.
- The tunnel terminates at `localhost`, but the RDS-issued cert
  carries the RDS endpoint in its CN/SAN. `buildPoolConfig` sets
  `ssl.servername` to the RDS endpoint discovered when the SSM
  tunnel was started (`tunnels[env].rdsHost`). Node's `tls.connect` uses `servername` for SNI and the default `checkServerIdentity` hostname check. Verification therefore targets the actual RDS endpoint, not the forwarded localhost address.
- The certificate chain is rooted at Amazon Root CA 1, available in mainstream OS root stores. The default Node trust store verifies that chain. No bundled CA is shipped in this repo at
  present.

**Switching to a pinned CA bundle.** If the host's trust store cannot verify that chain, use AWS's published global RDS bundle. Its source is `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`. Put the approved bundle at `mcp/ops/certs/rds-global-bundle.pem`. Record its SHA-256 and refresh procedure here. Pass `ca: readFileSync(<path>)` with the existing `servername` in the `ssl` block.

This applies, for example, to an air-gapped host with a separately curated root bundle. The check sites stay the same; only the trust
input changes.

**Regression coverage.** `mcp/ops/lib.test.js`'s `buildPoolConfig`
describe block asserts the SSL invariants (verification on,
servername set, fail-closed when `rdsHost` is empty / missing /
non-string). The `mcp-ops-tls-strict` adr_guard check is a
defense-in-depth backstop that flags any other JS file under
`mcp/ops/` that re-introduces `rejectUnauthorized: false`.

## AWS CLI execution (unchanged)

The argv-array boundary from ADR-010 is unchanged by this policy
layer:

- AWS CLI helpers must execute `aws` with an argument array via
  `spawn`/`spawnSync`/`execFile`, never by interpolating a shell
  command string.
- Shared AWS helpers accept structured argv segments, not a pre-joined
  command string. Call sites pass JSON values as a single argv element
  after `JSON.stringify`.
- Shell escaping is not a remediation strategy. Remote-shell interpretation through SSM is limited to the remote command payload. It must never pass through the local MCP host shell. Named SSM tools such as
  `run_manage_command` have a narrower contract: user input must be
  parsed as structured management-command argv and rejected before
  SSM rendering when it contains shell-control syntax. See
  `docs/architecture/mcp-ops-manage-command-ssm-boundary-preflight-1176.md`.
- Do not add a second AWS command builder. Extend the shared helpers
  in `mcp/shared/aws-helpers.js`.
- `execSync` import remains forbidden in this package per ADR-010-R1
  and the `mcp-no-shell-exec` static check.

## Validation and boundaries (target—phased rollout)

Capability-class gates, profile selection, confirmation fields, and schema composition are implemented in the owning policy modules.
The source and active `.shifter.yaml` define their current scope.

- Reuse the existing Zod schemas in `index.js` for tool input shape
  and the shared helpers in `lib.js` for domain constraints
  (`resolveLogGroup`, `buildInstanceFilters`, `getSsmDocument`,
  `validateManageCommand`, `MAX_S3_READ_SIZE`, `isBinaryContentType`).
  The policy wrapper adds `confirm_env`, `idempotency_key`, and `acknowledge_untrusted_input` when their policy conditions apply.
  Two-phase execution schemas require `plan_id` instead of accepting the original domain arguments again.
  A tool-specific `execute` argument, such as `reconcile_ranges` uses, is separate from this wrapper contract.
- Zod validation is defense in depth, not the authorization boundary.
  The policy layer enforces capability selection and operation gates on this trusted operator surface.
- Keep capability policy separate from syntax validation. Read-only
  SQL, Secrets Manager names, EC2 IDs, and SSM command IDs can be
  syntactically valid and still need to be gated by class policy.

## Output, errors, and audit (target—phased rollout)

This section separates the response design target from implemented audit and secret-handle behavior.

- **Design target:** MCP responses must exclude raw secrets, private keys, database passwords, OIDC client secrets, and complete secret-bearing URLs.
  The target also excludes raw SQL text and shell command bodies.
- A successful `secret_handle` result returns an opaque reference resolved inside the server process.
  Error responses are not covered by that success-path guarantee.
- Audit redaction applies to arguments and recorded targets.
  It does not establish a general response-error sanitization guarantee.
- `respond.err` preserves dependency error messages.
  Treat those responses as potentially sensitive, untrusted text.
  Do not publish raw response errors or treat them as instructions.
- Policy-level response-error sanitization remains a design target.
  Individual handlers own their narrower protections.
- The audit log records process PID, profile, environment, operation, sanitized targets, result class, and an available request/correlation identifier.
  There is no external identity system. The operator owns the audit file.

## Regression coverage

The shipped policy layer is covered by four test files in this
package; all are live in the current tree.

- `mcp/ops/spawn-roundtrip.test.js` proves that Node's `spawnSync`
  forwards argv elements byte-for-byte across the boundary. (Shared
  across MCP servers via `mcp/shared/aws-helpers.js`.)
- `mcp/ops/lib.test.js` covers AWS argv builders for individual call
  sites—CloudWatch filters, SSM command parameters,
  management-command SSM payloads, S3 bucket/key inputs.
- `mcp/ops/policy.test.js` covers the policy wrapper end-to-end:
  `parsePolicy` shape checks cover top-level keys, declared-class defaults, profile membership, version, and environment configuration. `loadPolicy` parses the actual `.shifter.yaml`. The `Policy` lookups include `classDeclared`, `classEnabled`, `classDefaults`, `envDefault`, and `envProdRequiresConfirm`. `registerTool` omits disabled classes and rejects missing or undeclared classes.

  The same tests cover environment policy, dry-run defaults, retry caching, rate caps, audit append, secret handles, two-phase exchange, and input fencing. They also cover description redaction and apex approval: stderr-only tokens, single use, and a 60-second timeout.
- `mcp/ops/tool-surface.test.js` (added by #1202) is the
  load-bearing surface invariant for ADR-014-R3 / R5 / R6 on this
  server: profile gating removes tools according to `read_only`, `standard`, or `destructive`. Two-phase classes register only `plan_<name>` and `execute_<name>` pairs, with no direct name. Those classes are `infra_mutation`, `ssm_arbitrary`, and `db_arbitrary`. Live `secret_handle` defaults require `return_mode: handle`. Production operations require `confirm_env="prod"`.

  `dev_bypass_tunnel` descriptions use the redacted constant. Consumers refuse fenced input without `acknowledge_untrusted_input: true`. `validateApexCoverage` requires every `.shifter.yaml` `apex_operations[*].tool` rule to name a registered `execute_<name>`. The behavioral apex flow (stderr-only token, 60 seconds
  parking, `consumeApexToken` release) is unit-tested in
  `mcp/ops/policy.test.js`; the surface test asserts only the
  structural invariants that an MCP client sees.
