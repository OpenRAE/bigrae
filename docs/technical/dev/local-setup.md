# Local Development Setup

Use this how-to guide to run the BigRAE portal on a local workstation.
This test configuration does not deploy cloud resources or qualify a live range.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- Node 20.19 or later, with npm
- The Python version declared by `shifter/shifter_platform/pyproject.toml`

Start from the repository root in a development checkout.
Keep deployment credentials and production configuration out of this local test environment.

## First run

1. Install the platform dependencies:

   ```bash
   cd shifter/shifter_platform
   uv sync --group dev
   ```

2. Build the SPA so that Django can serve it:

   ```bash
   (cd frontend && npm ci && npm run build)
   ```

3. Prepare the local database and start the server:

   ```bash
   TESTING=1 TEST_DB_BACKEND=sqlite DJANGO_DEBUG=true uv run python manage.py migrate
   TESTING=1 TEST_DB_BACKEND=sqlite DJANGO_DEBUG=true uv run python manage.py runserver 127.0.0.1:8000
   ```

The portal runs at `http://localhost:8000`. The commands explicitly select test mode, `DEBUG`, and SQLite.
The local database is `shifter/shifter_platform/db.sqlite3`.
These explicit settings override an ambient database or debug selection.

Sign in at `http://localhost:8000/dev-login/`.
Development login requires `DEBUG` or `ENVIRONMENT=development`, plus a loopback peer or configured admin CIDR.
The guard checks the direct peer address, not `Host` or `X-Forwarded-For`.
Do not expose this server through a public ingress or broaden the allowlist to bypass the guard.
Development login does not grant arbitrary native administration authority.

## Tests and checks

Select the test modules or cases for the changed behavior.
For example, from `shifter/shifter_platform`, check development-login admission:

```bash
TEST_DB_BACKEND=sqlite uv run pytest tests/config/test_dev_auth.py -n0 --no-cov
```

Use the [command matrix](../../dev/testing.md#command-matrix) to find each lane and its CI owner.
Keep full suites in CI. The matrix records full-lane commands for reproduction; it is not a local checklist.
Use `pre-commit run` for staged-file hygiene before a commit.
Use the [documentation instructions](https://github.com/OpenRAE/bigrae/blob/dev/CONTRIBUTING.md#documentation) for explicit-path prose checks.

## Troubleshooting

- Port in use: check with `lsof -i :8000`, or start on another port with
  `TESTING=1 TEST_DB_BACKEND=sqlite DJANGO_DEBUG=true uv run python manage.py runserver 8001`.
- Missing dependencies: run `uv sync --group dev` again from
  `shifter/shifter_platform`.
- Development-login 403: check the test configuration and actual peer address.
  Do not substitute a forged request header or disable the guard.
- Empty or denied workspace: check the actor and native grants through the supported administration interface.
- Stop the local server with `Ctrl+C` before running browser targets that recreate its SQLite database.
