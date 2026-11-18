# Range Functional Smoke

Use this how-to guide to verify a participant's terminal and Guacamole access on an existing range.
The harness sends real requests to a deployed tenant.
It is operator-invoked and gates no deployment.
The [harness reference](https://github.com/OpenRAE/bigrae/blob/dev/uat/range-functional-smoke/README.md) describes exact evidence and controls.

## What it closes

A TCP probe to ports 22 and 3389 cannot prove a working participant session.
This protocol requires terminal output from the guest and a Guacamole client protocol exchange.
It uses the real HTTP, WebSocket, and Guacamole paths without manual browser steps during execution.

## Preconditions

- Authority to exercise the selected deployed tenant.
- A healthy deployment; image boot and deployment health are separate checks.
- An existing range owned by the selected actor, active and `ready`.
- An instance whose authored `participant_access` declares the channel being tested.
- One valid participant actor source below.

A missing or unready range fails the run. It is never a successful skip.
This harness does not provision or destroy the range.

## Actor sources

Choose exactly one source:

- **Captured session:** log in normally and place the `sessionid` value in a mode-0600 file.
  Pass only its path with `--session-file`.
  The loader refuses group-readable or world-readable files.
- **Front-door login:** use an operator-provisioned Identity Platform account with enrolled TOTP.
  Supply `--email` and `--credential-env`.
  The harness reads `SMOKE_PASSWORD`, `SMOKE_TOTP_SECRET`, and `SMOKE_API_KEY` from the environment, never from arguments.

The front-door route performs password sign-in, TOTP verification, and the product's `POST /auth/identity/session/` exchange.
The product checks verified email and enrolled MFA before establishing the application session.
Neither route uses a custom-token, superuser, or smoke-only authentication bypass.

Do not use `/dev-login/` as live qualification evidence.
That development-only endpoint also has a direct-peer admission guard.

## Running it

1. Obtain the required actor source and confirm range ownership.
2. Install the harness dependencies:

   ```bash
   cd uat/range-functional-smoke
   uv sync --group dev
   ```

3. Run against the authorized target with synthetic selector values:

   ```bash
   uv run range-functional-smoke \
     --origin https://portal.example.com \
     --environment development \
     --target-role attacker \
     --protocol rdp \
     --session-file ~/.shifter/smoke.session
   ```

4. Inspect every check in the report before accepting its verdict.
5. Retain the sanitized result with the exact source and deployment revisions in the operator's evidence location.

`--protocol` defaults to `rdp`; the terminal check already exercises SSH.
Production-looking targets require explicit `--allow-production` acknowledgment.
HTTPS is required. `--allow-plaintext-loopback` permits plaintext only for a loopback fixture.
Do not use that option to relax a deployed tenant's transport policy.
Guest identifiers are opaque segments; the harness encodes reserved URL characters.

## Reading the verdict

Exit status `0` means all required checks passed.
A failed, blocked, skipped, timed-out, or errored check is not a pass.
The report separately records range readiness, target selection, terminal admission, terminal exchange, and Guacamole evidence.

- `terminal_nonce_exchange`: input produced the expected output from the guest shell.
  A WebSocket upgrade or input echo is insufficient.
- `guacamole_session_connected`: the browser tunnel supplies its identifier, accepts display synchronization, and sends a further display update.
  Bootstrap success and one-time URL delivery alone prove credential issuance.

The gateway consumes the internal `ready` instruction before opening the browser tunnel.
The checker follows the [Apache browser client's synchronization behavior](https://guacamole.apache.org/doc/1.6.0/guacamole-common-js/main_webapp_modules_Client.js.html).
It acknowledges synchronization and image data.

If bootstrap passes but connection fails, inspect the connection error and protocol result before assigning a cause.
Check range readiness, authored target selection, and actor authority before retrying.
Pace repeated TOTP logins; Identity Platform can return `QUOTA_EXCEEDED`.
Do not bypass a failed guard or change tenant policy to obtain a pass.

The report contains identifiers and provenance.
It excludes cookies, tokens, Guacamole URLs, SSH keys, private addresses, raw bodies, tracebacks, and terminal output.
Keep any additional diagnostic evidence in the operator's private evidence location.

## Scope

This proves the participant access journey for the selected range and run.
Use [range escape validation](../ops/range-escape-validation.md) for isolation.
Use [event capacity qualification](../ops/gcp-event-capacity.md) for the selected shared-service load profile.
External packs own their scenario-content acceptance evidence.
