# Range functional smoke (#987)

This reference describes the harness's evidence and safety contracts.
Use the [operator how-to guide](../../docs/qa/range-functional-smoke.md) to prepare, run, interpret, and recover a check.
The harness drives a deployed tenant through its public participant interfaces.
It takes no cloud role, provisions no range, and destroys no range.
It is on demand and gates no deployment.

## Why it exists

This explanation distinguishes reachability from usable access.
A TCP probe cannot prove terminal execution or a Guacamole client session.

| Check | Live range | Terminal and Guacamole |
| --- | --- | --- |
| [Built-image stack smoke](../../scripts/stack-smoke/README.md) | No | Outside its scope |
| Post-deploy range smoke | Yes | TCP reachability only |
| This harness | Yes | Real participant exchange |

## What counts as a pass

Every required check must pass.
A missing, blocked, skipped, timed-out, or errored check is never a pass.

| Check | Sufficient evidence |
| --- | --- |
| `range_owned_ready` | Owner-scoped projection reports an active, ready range |
| `target_selected` | Authored logical role resolves to an instance offered for terminal access |
| `terminal_socket_open` | Routed consumer accepted the socket |
| `terminal_nonce_exchange` | Input produced matching output from the guest shell |
| `guacamole_bootstrap_accepted` | HTTP 202 proves queue admission only |
| `guacamole_bootstrap_succeeded` | The server minted a signed URL |
| `guacamole_url_delivered` | This client consumed the one-time URL |
| `guacamole_session_connected` | Browser tunnel identifier, display synchronization, and a later display update |

Only terminal exchange and the complete Guacamole protocol exchange prove the required access behavior.
Bootstrap success alone proves credential issuance.
The checker acknowledges synchronization and image data; the gateway consumes internal `ready` before opening the browser tunnel.

### The echo hazard

A shell can echo input without executing it.
The split command `echo "SMOKE""<nonce>"` distinguishes echoed input from the joined output `SMOKE<nonce>`.
`tests/test_terminal.py::TestEchoHazard` protects this distinction.

## Running it

Follow the [operator procedure](../../docs/qa/range-functional-smoke.md#running-it).
The CLI accepts exactly one actor source:

- `--session-file`: a normal-login session key in a mode-0600 file.
- `--email` with `--credential-env`: front-door Identity Platform password and enrolled TOTP login.
  Secrets come from `SMOKE_PASSWORD`, `SMOKE_TOTP_SECRET`, and `SMOKE_API_KEY`, never arguments.

Use `uv run range-functional-smoke --help` for the complete current argument reference.
`--origin` and `--environment` are required.
The logical target role defaults to `attacker`; the Guacamole protocol defaults to `rdp`.
The default terminal-exchange, bootstrap, and total deadlines are 45, 90, and 600 seconds.
`--evidence` additionally writes the rendered report to a selected path.
Exit status `0` means pass, `1` means failed checks, and `2` means invalid configuration or actor-source input.

Production-looking targets require `--allow-production`.
HTTPS is required for the origin and server-returned URLs.
`--allow-plaintext-loopback` permits HTTP/WebSocket plaintext only for a loopback fixture.
The harness carries replayable session material and Guacamole tokens; plaintext would expose them.
Pace repeated logins because Identity Platform can return `QUOTA_EXCEEDED`.

## Design boundaries

The profile carries logical role and protocol selectors, not connection material.
Host, port, user, key, and password resolution stay inside the portal.
The existing example range belongs to its creator and is never destroyed by this harness.

The harness uses no development-login, custom-token, superuser, or smoke-only authentication bypass.
The product rechecks verified email and enrolled MFA for the Identity Platform session exchange.
Development login's separate DEBUG/environment and direct-peer guards remain outside live qualification.

Evidence excludes cookies, tokens, Guacamole URLs, private addresses, raw bodies, tracebacks, and terminal output.
Run the harness only with operator authority for the selected tenant and actor.
Do not alter authorization or transport policy to make a failed check pass.

## Tests

Select targeted deterministic modules for the changed behavior, for example:

```bash
uv run pytest tests/test_terminal.py tests/test_guacamole_protocol.py -q
```

The test estate covers profile safety, target selection, nonce matching, Guacamole states, TOTP derivation, redaction, and verdict composition.
CI owns the full harness suite.
Operator runs against a deployed tenant establish live evidence; mocked application behavior cannot qualify that journey.
