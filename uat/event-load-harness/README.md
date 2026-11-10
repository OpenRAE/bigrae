# Event Load Harness (#926)

This reference describes the harness configuration, traffic profiles, safety controls, and evidence limits.
Its how-to sections cover installation and an authorized run.
The harness drives a deployed BigRAE portal through real HTTP and WebSocket contracts.
It measures client latency, errors, and WebSocket close codes, then renders a sanitized concurrency-envelope report.

It supplies measured evidence for the analytical capacity envelope in `docs/architecture/terminal-websocket-capacity-847.md`.
Issue #846 uses that evidence for the event baseline; #910 uses it for portal sizing. Design constraints are recorded in
`docs/architecture/event-load-harness-preflight-926.md`.

A sample of the output is committed at
[`sample-envelope-report.md`](sample-envelope-report.md) (illustrative
placeholder numbers, not a real run).

## Design

The load-generation core is platform-agnostic: it targets the application's
HTTP/WebSocket endpoints independently of its cloud provider.
That independence does not qualify a deployment backend. Provider-metrics collection is an optional, swappable
adapter behind `event_load_harness.metrics.base.MetricsAdapter`, so a platform
change replaces one adapter rather than the harness.

```
cli.py        one-command entrypoint: orchestrates load -> metrics -> report
config.py     validated run config (https-only, prod refusal, bounds)
profiles.py   named traffic mixes + the route catalog (active vs deferred)
auth.py       actor sources: 0600 manifest, dev-login generator, ctfd-csv (deferred)
auth_http.py  live authenticator (replays the real session flow)
routes.py     route->endpoint contract + the live executor
runner.py     async virtual-user orchestration (ramp, concurrency, duration)
stats.py      per-route p50/p95/p99, error and websocket close-code distributions
report.py     sanitized envelope renderer + heuristic conclusion
metrics/      client-only (default) and aws (thin plug) adapters
```

It does **not** import the Shifter Django application. It runs as an external
client, so it stays runnable without the app installed.

## Install

```sh
cd uat/event-load-harness
uv sync                # core (httpx, websockets)
uv sync --extra aws    # add boto3 for the AWS metrics adapter
uv sync --extra gcp    # add Google Cloud Monitoring for the GCP event gate
```

## Run

Obtain operator authority for the exact target, workload, and test actors before generating load.
Confirm the target revision and recovery plan. Keep private evidence in its owning location.

One command produces the report. Provide config via flags or a TOML file (flags
override the file):

```sh
uv run event-load-harness \
  --target-url https://<deployed-dev-host> \
  --confirm-host <deployed-dev-host> \
  --environment dev \
  --profile portal-core \
  --concurrency 150 --ramp-seconds 60 --duration-seconds 600 \
  --actor-source manifest --actor-manifest ./actors.toml \
  --metric-source client-only \
  --report-path out/envelope.md
```

`--confirm-host` must match the target URL host. It acknowledges the exact host for this run.
A mismatched host is refused before load generation. Use `--allow-production` instead for an intended production
target, or `--allow-insecure-localhost` for an `http://localhost` tunnel.

Equivalent `run.toml`:

```toml
target_url = "https://<deployed-dev-host>"
environment = "dev"
profile = "portal-core"
concurrency = 150
ramp_seconds = 60
duration_seconds = 600
actor_source = "manifest"
actor_manifest_path = "actors.toml"
metric_source = "client-only"
report_path = "out/envelope.md"
confirm_host = "<deployed-dev-host>"
```

```sh
uv run event-load-harness --config run.toml
uv run event-load-harness --list-profiles    # list traffic profiles
```

Stop the run if tenant health degrades. Investigate before increasing concurrency.
Use the owning operations runbook for recovery and keep diagnostic evidence private.

## Profiles and routes

`portal-core` exercises the path that failed in the May event: authenticated
page traffic, range-status polling and websocket, browser terminal websockets,
and Guacamole RDP bootstrap.

The route catalog (`profiles.ROUTE_CATALOG`) also lists **deferred** route
classes (`ctfd:*`, `ctf:*`) that document the seam for follow-up work. The
native-CTF submission/scoreboard profile that feeds #850 is a future
profile-plus-executor addition, not a rewrite. A profile cannot select a
deferred route until its executor lands.

## Actors (identities)

Load must run as many distinct authenticated users, never one shared admin
session. Three sources:

- `manifest`: a **0600** TOML file of participant credentials or sessions. The
  loader refuses any group- or world-readable file.

  ```toml
  [[actor]]
  email = "participant1@example.com"
  password = "..."
  user_type = "ctf_participant"

  [[actor]]
  email = "participant2@example.com"
  session_cookie = "sessionid=...; csrftoken=..."
  ```

- `dev-login`: generates actors that drive the documented `/dev-login/`
  endpoint. Valid only where dev-login is enabled (deployed dev). Use
  `--actor-count` to set how many. The harness never broadens
  `DEV_LOGIN_ALLOWED_*` or makes this work against production.

- `ctfd-csv`: deferred with the CTFd surface.

## Safety

- **Target**: must be an explicit `https://` URL. Every non-localhost target
  must be positively acknowledged: pass `--confirm-host` matching the target
  host, or `--allow-production` for an intended production target. An
  unacknowledged or mislabeled host is refused rather than hit by accident.
  `http://` is allowed only for `localhost` with `--allow-insecure-localhost`
  (tunnel profile). The harness does not relax `ALLOWED_HOSTS`, WAF, TLS, or
  origin policy.
- **Secrets**: credentials come from the 0600 manifest, never from argv. The
  report renderer runs a sanitization scan and refuses to write output that
  matches a secret pattern. Do not commit `out/`, `run*.toml`, or `actors*.toml`
  (all gitignored).
- **Load on shared infrastructure**: running against shared dev puts real load
  on shared infra. Treat the live run as an operator-gated action.

## Metrics adapters

- `client-only` (default): no provider credentials. The report lists the
  provider signals it did not collect as explicit gaps.
- `aws`: thin CloudWatch plug. Pass the resource identifiers you want collected;
  anything omitted, or any failed query, becomes a named gap rather than a
  guessed number. Reads telemetry only; issues no mutating calls.

  ```sh
  uv run event-load-harness ... \
    --metric-source aws --region us-east-2 \
    --aws-alb app/<portal-alb>/<id> --aws-target-group targetgroup/<portal-tg>/<id> \
    --aws-asg <portal-asg> --aws-name-prefix <env>-portal \
    --aws-rds <portal-db> --aws-redis <portal-redis>
  ```

  `--aws-target-group` (with `--aws-alb`) collects ALB `RequestCountPerTarget`
  (the portal scale-out signal), which AWS publishes under the LoadBalancer +
  TargetGroup dimension pair, and `--aws-name-prefix` collects the app-emitted
  `Shifter/PortalCapacity` worker busy ratio and terminal-session gauges (#940).
  All ARN suffixes are exposed as Terraform outputs of the portal `alb` module.

  For #853, the AWS adapter records RDS `DatabaseConnections` average and peak
  values, plus a lower-bound connection churn proxy derived from
  sample-to-sample active-connection deltas. CloudWatch does not expose exact opens or closes per second.
  Short-lived cycles between samples remain invisible. The report labels this value as a proxy.

- `gcp`: the strict event-capacity adapter. It reads GKE restart and CPU metrics, plus Cloud SQL and Redis connection and health metrics.
  It also reads HTTPS load-balancer latency and response classes, effective guacd readiness, and backend-service health. Missing data is a named gap and fails the strict gate.

## GCP event gate (#1816, #2502)

The `guacamole-event-gate` profile is a qualification gate for a GCP
shared-service capacity profile, not a synthetic portal-core approximation. It
runs the selected profile's authored budget at that profile's participant count:
`--capacity-profile-id gcp-shared-v1-p300` requires `--concurrency 300`. It requires one distinct mode-0600 manifest entry per participant with `email`, `password`, `totp_secret`, and `api_key`.
Each participant completes Identity Platform/TOTP login, product session exchange, range selection, and versioned Guacamole bootstrap.
The WebSocket tunnel then completes display synchronization and a 120-second continuous hold.

The complete scale-up, drift, invocation, thresholds, and scale-down procedure
is documented in
[`docs/ops/gcp-event-capacity.md`](../../docs/ops/gcp-event-capacity.md).

## Database connection churn (#853)

The report includes a `Database connection posture (#853)` section. It keeps
the current deployed Django posture visible (`CONN_MAX_AGE=0`) and compares it
with same-window RDS metrics and client tail latency. Keep the current posture when connection churn does not move with RDS CPU or portal p95/p99 latency.
Consider the DB connection lifecycle only when churn, RDS pressure, and user-visible latency move together during stepped-concurrency runs.

Do not use the harness output alone to turn on persistent connections. First
check the capacity math for the target runtime:

```text
portal replicas * worker/process count * Django connection contexts
```

That total must fit under the database max-connection budget with failover and
background-worker headroom.

## Portal autoscaling scale-out verification (#940)

This is the documented acceptance run for #940: prove portal scale-out reacts to
request-path saturation *before* average EC2 CPU pins. It needs an ASG-enabled
environment (`enable_autoscaling = true` and `portal_capacity_metrics_enabled =
true`, for example prod); the committed dev tfvars run a single instance and
cannot scale out.

1. Resolve the targets from the portal Terraform outputs: the `alb` module's
   `alb_arn_suffix` / `target_group_arn_suffix`, the portal ASG name, and the
   environment `name_prefix` (for example `prod-portal`).
2. Run a stepped-concurrency profile that drives request-path saturation against
   the deployed target, collecting AWS metrics for the run window:

   ```sh
   uv run event-load-harness --target-url https://<portal-host> \
     --confirm-host <portal-host> --profile portal-core \
     --concurrency <stepped> --ramp-seconds <r> --duration-seconds <d> \
     --metric-source aws --region us-east-2 \
     --aws-alb <alb_arn_suffix> --aws-target-group <target_group_arn_suffix> \
     --aws-asg <portal-asg> --aws-name-prefix <env>-portal
   ```

3. Inspect the report and `<env>-portal-portal-capacity` CloudWatch dashboard.
4. Confirm `RequestCountPerTarget`, `TargetResponseTime`, and `WorkerBusyRatio` rise.
5. Confirm the ASG adds capacity before `AWS/EC2` `CPUUtilization` reaches the guardrail threshold. The target-tracking policies
   own scale-out and scale-in; the worker-busy-ratio alarm adds an app-saturation
   scale-out. Any unconfigured target is reported as a named gap, never a guess.

## Output

The envelope report records the target, run parameters, and deployment shape.
It includes per-route requests, errors, p50/p95/p99 latency, and WebSocket opens, drops, close codes, and reconnects.
It includes same-window provider metrics or named gaps, DB connection posture, and first-mover attribution.
Its supported-concurrency conclusion identifies the limiting factor and a sizing implication for #910. Unknown fields render as `unknown` rather than a
guess.

The conclusion is a heuristic first pass from a single run. Bounding the true
ceiling and margin needs a stepped-concurrency sweep; re-run at increasing
`--concurrency` and compare reports.

## Tests

Use targeted modules for the changed behavior, for example:

```sh
uv run pytest tests/test_config.py tests/test_auth.py tests/test_report.py -q
```

CI owns the complete suite.
Tests cover configuration, statistics, report sanitization, close codes, profiles, routes, manifest permissions, and runner scheduling.
The runner uses an injected executor at its external boundary.
Operator runs establish live HTTP/WebSocket evidence against the selected deployment.
A deterministic source test does not qualify a live tenant.
