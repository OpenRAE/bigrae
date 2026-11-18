# Built-image stack smoke (#922)

This explanation describes the built-image fixture and its trust boundaries.
The how-to section covers an authorized local run; the parameter table is reference.
`stack_smoke.sh` boots the production portal image through its real `entrypoint.sh`.
It uses local PostgreSQL, Redis, and ElasticMQ doubles with released OpenFGA.
It verifies runtime contracts that source-tree tests cannot establish.

The fixture needs no cloud credentials.
Its AWS queue surface uses `AWS_ENDPOINT_URL` with synthetic credentials against local ElasticMQ.
A fixture pass does not qualify a live range, terminal, or Guacamole session.

## What it asserts

1. **Image build:** the production Dockerfile uses context `./shifter`.
   It installs dependencies and runs `compilemessages` and `collectstatic` as non-root `appuser`.
2. **Native activation:** the fixture runs the released OpenFGA datastore migrations and applies the chart's separate admin/runtime SQL duties.
   It starts TLS servers with distinct tokens and publishes the image's authorization model through the admin API.
   Before activation, a normal image command must fail the real entrypoint gate.
   A bounded maintenance process creates a distinct synthetic human operator and native provider binding through Management services.
   It then calls `identity_cutover plan`, `apply`, `identity_cutover_bootstrap`, `verify`, and `identity_runtime_check`.
   Trusted cutover facts explicitly set `bootstrap_personal_token_eligibility: true`; the plan digest retains that choice.
   Bootstrap writes and verifies that separate grant. An administrator role alone does not enable token use.
   The fixture performs no ordinary self-grant, activated-state insertion, or authorization-provider replacement.
3. **Boot:** a dedicated process runs migrations once.
   Every long-running container uses `SKIP_MIGRATIONS=1`, matching the chart's separate migration Job.
   The entrypoint waits for the database and executes production Gunicorn/Uvicorn ASGI as `appuser`.
4. **Readiness:** `/health/` returns HTTP 200 from the real dependency-aware `django-health-check` registry.
   The checks cover database, cache, storage, and the Redis channel layer.
5. **Native catalog:** after readiness, a real OIDC operator login establishes the session used by `issue_personal_token`.
   The owning service issues a Knox token with installation content read/manage/publish scopes through the released policy service.
   Its private bearer file goes to `bootstrap_inbox_catalog --credential-file`.
   Shipped sources must have that native owner, installation custody, conformance receipts, and explicit publication.
   A staff flag or implicit deployment actor cannot authorize registration.
6. **First login:** a real authorization-code flow uses a local Cognito-shaped provider double.
   It follows `/login/`, `/oauth2/authorize`, and `/oidc/callback/` through `mozilla_django_oidc` and `ShifterOIDCBackend`.
   Before the flow, the first-login user, human Principal, ProviderBinding, and PrincipalSession must be absent.
   Afterward, the native records bind to the verified `(issuer, subject)` and establish the reusable Django session.
7. **WebSocket:** the authenticated handshake passes `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and the `ws/notifications/` route.
   It uses the login-established session.
8. **Page renders:** the dashboard, range, terminal, settings, and help pages return HTTP 200 from the image.
   Every referenced local `/static/` asset and declared source map must resolve.
   These are the range-independent checks from #923 TEST-3; live terminal exchange and Guacamole remain outside scope.
9. **Workers:** the SQS worker and CTF scheduler boot from that image and produce their `/tmp/<name>-heartbeat` files.

The fixture orders activation before normal web readiness, token issuance, and inbox registration.
The separate first browser login then supplies WebSocket and page checks, followed by worker checks.
Operator and first-login identities remain distinct.
No browser user or session is seeded.
Maintenance mode is limited to operator setup and never reaches web, inbox, or worker containers.

### Local trust boundary

All identities, database passwords, provider keys, and tokens are synthetic and disposable.
The trusted host and Docker daemon control the fixture.
OpenFGA images and CLI use the integration harness's released digests.
Chart-owned SQL separates runtime and administration duties.

Only the runtime token and CA certificate enter application containers.
Token and identity-fact files use mode 0600 and are readable by the image user.
The admin token never enters application containers.
The disposable OpenFGA image can read its temporary TLS private key, as in the local integration fixture.
That key is not a production certificate. Admin API ports bind only loopback.

The OIDC provider is the only identity-provider double.
Its private-network HTTP transport is a local fixture assumption, not deployment configuration.

### Local OIDC provider double

`stub_idp.py` supplies the endpoint shapes derived by `config._oidc_settings`:
`/oauth2/authorize`, `/oauth2/token`, `/oauth2/userInfo`, and `/.well-known/jwks.json`.
It signs RS256 ID tokens bound to each request's `state` and `nonce`.
It rejects incorrect client identifiers or secrets, incorrect or absent redirect URIs, reused codes, and missing bearer tokens.

The double uses the image's Python interpreter, PyJWT, and cryptography packages.
It generates a fresh key pair at startup; no private key is committed.
Standard `login_hint` selects the explicit synthetic operator.
Without it, the double selects the separate first-login identity.
Codes and access tokens retain the exact subject and email so UserInfo cannot switch identities.

`oidc_login.py` uses a cookie jar and manual redirects through the real login and callback flow.
It runs inside the smoke network and resolves the portal and provider by name.
It addresses the portal's logical HTTPS origin with `Host` and `X-Forwarded-Proto: https` over the private HTTP transport.
This retains secure-cookie and redirect-URI behavior.

The captured session key goes into a mode-0600 file.
`ws_handshake.py` and `page_smoke.py` receive only its path through `--session-file`.
Session and token values never enter process arguments.

## Run it locally

CI owns the complete image smoke gate.
Do not run it only to check prose or as a routine targeted source test.
An explicit local image-validation task requires Docker, uv, Python 3, curl, and OpenSSL.
Run from the repository root:

```bash
bash scripts/stack-smoke/stack_smoke.sh
```

The script refuses existing container and network names, then creates a private Docker network.
On exit, including failure, it removes only resources labeled as owned by that run.
A failed assertion produces a bounded log tail and nonzero status.
Investigate the failed contract before retrying; do not remove unrelated containers to clear a name conflict.

## Parameters (extensibility seam)

Environment variables override the scalar parameters.
`SMOKE_WORKER_SPECS` is one list for workers and schedulers.
A new fixture variation extends parameters instead of copying the workflow.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SMOKE_IMAGE` | `shifter-portal:stack-smoke` | Image tag to build/run |
| `SMOKE_BUILD` | `1` | Build the image (`0` = reuse `SMOKE_IMAGE`) |
| `SMOKE_DOCKERFILE` | `shifter/shifter_platform/Dockerfile` | Dockerfile path |
| `SMOKE_CONTEXT` | `shifter` | Docker build context |
| `SMOKE_WEB_PORT` | `18000` | Host port mapped to the web container's 8000 |
| `SMOKE_HEALTH_PATH` | `/health/` | Readiness path to poll for 200 |
| `SMOKE_WS_PATH` | `ws/notifications/` | Routed websocket consumer path |
| `SMOKE_PAGES` | SPA root/range/terminal/settings/help | Space-separated authenticated page paths to render + asset-check |
| `SMOKE_BOOT_TIMEOUT` | `180` | Seconds to wait for readiness |
| `SMOKE_HEARTBEAT_TIMEOUT` | `120` | Seconds to wait for each heartbeat |
| `SMOKE_WORKER_SPECS` | cms worker + ctf-scheduler | `name\|heartbeat_file\|command` per line |
| `SMOKE_PG_IMAGE` / `SMOKE_REDIS_IMAGE` / `SMOKE_ELASTICMQ_IMAGE` | pinned | Dependency double images |
| `SMOKE_IDP_PORT` | `8080` | Port the local OIDC provider double listens on |

The OIDC fixture uses one parameter set for client identity, issuer, auth domain, callback, and synthetic claims.
Another version or claim set should extend that fixture rather than introduce another harness.

## CI

`.github/workflows/_quality.yml` owns the `stack-smoke` job.
The caller's `run_stack_smoke` input and the quality path classifier select it.
`deploy.yml` selects it for portal-image, platform-infrastructure, smoke-harness changes, or manual dispatch.
The job also checks `skip_tests` and the classified quality units before execution.
Ordinary prose changes do not by themselves select the image build.
See [testing reference](../../docs/dev/testing.md) for the complete lane owner.
