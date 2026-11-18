# installation

This reference describes the BigRAE installation parser and its contributor commands.
For operator installation, use [Install on Google Cloud](../../docs/getting-started/install-gcp.md).
Published AWS installation support is planned.

`bigrae-config` and `bigrae.yaml` are the current names.
`shifter-config` and `shifter.yaml` remain compatibility aliases.
Conflicting root configuration files are rejected.
The `.shifter.yaml` operations policy is a separate file.

`bigrae.yaml` is a user-authored file at the repository root. It selects one
backend bundle and provides deployment-level settings. The installation package
is the authoritative parser for that file.

## AWS EKS lifecycle

The canonical AWS platform package is the shared Helm chart on EKS. After
validating `backend: aws`, deploy through the typed bundle entrypoint:

```console
./scripts/bootstrap/deploy.py eks-deploy --config bigrae.yaml \
  --images .shifter/images.json --profile operator
```

The images JSON contains attested `repository@sha256:<digest>` identities, not
tags. Teardown is explicit and scoped to the isolated EKS root:

```console
./scripts/bootstrap/deploy.py eks-teardown --config bigrae.yaml --profile operator
```

## Supported Backends

| Backend | Profiles | Required secrets | Settings validation |
| --- | --- | --- | --- |
| `aws` | `prod`, `dev` | `django_secret_key`, `db_password` | Closed model: `region` (required). |
| `gcp` | `prod`, `dev` | `django_secret_key` | Closed model: `project_id` and `region` (required), plus the optional deployment-input blocks below. |

Both the `aws` (#728) and `gcp` (#729) entries validate their `settings` against a closed
model and each secret reference against a machine-readable grammar; unknown keys fail fast.
For AWS, `region` is required. For GCP, `project_id` and `region` are required.

### GCP settings

| Key | Required | Notes |
| --- | --- | --- |
| `project_id` | yes | GCP project id (6-30 chars, a lowercase letter then lowercase letters/digits/hyphens, no trailing hyphen). |
| `region` | yes | GCP region/location, for example `us-central1`. |
| `range_cells` | no | GCE range-cell placement: `backend` (`gce` default or `gdc`), `zone`, `zones`, `project_id`, `host_identity_pool_size`, `private_google_access`, and `image_key_profiles` (32,768 bytes maximum). |
| `participant_openvpn` | no | `enabled` (default `false`) deploys the shared participant OpenVPN pool. |
| `ctf_content_bucket` | no | The private CTF content bucket name. |
| `operator_bootstrap` | no | The first Identity Platform operator: `enabled` (default `true`), `admin_email`, `admin_password_secret_ref` (`projects/<project>/secrets/<id>`), `staff_emails`, and `superuser_emails`. `enabled` requires `admin_email`. |
| `post_deploy_smoke` | no | `user_email`: the existing portal account for the advisory post-deploy smoke. Empty skips the smoke. |
| `release_trust` | no | `github_repository_id` and `github_owner_id`: the numeric IDs of the repository that signs the release provenance. The GitHub-less deploy requires it. |

The deployment-input blocks hold the GCP deploy inputs that GitHub variables and
secrets held before #2571 (`settings_gcp_deploy.py`). The GCP deploy command
(`scripts/bootstrap/deploy.py gcp-deploy`) projects them onto the runtime
environment and the platform Terraform values. The values are public
identifiers or secret references, never secret values.

The GCP `django_secret_key` reference must be a Google Secret Manager resource name
(`projects/<project>/secrets/<name>/versions/<version>`), a GitHub Actions secret name, an
environment variable, or the literal `prompt`.

`range_egress` is the shared cross-backend egress policy (see [Render](#render)). Validation is the same for every backend. It is separate from backend-specific settings.
## Config File

Start from one of the checked examples:

```bash
cp shifter/installation/examples/aws.yaml bigrae.yaml
uv run --project shifter/installation bigrae-config validate bigrae.yaml
```

Use `examples/gcp.yaml` for GCP.

## Init

`bigrae-config init` scaffolds a starting `bigrae.yaml` from the checked example
for a backend, so you begin from a valid, backend-shaped config instead of a blank
file. It is local-only: it copies committed example text, authenticates to nothing,
writes no secrets, and touches no cloud API.

```bash
# List the backends that ship an example.
uv run --project shifter/installation bigrae-config init

# Scaffold ./bigrae.yaml for a backend (add --force to overwrite an existing file).
uv run --project shifter/installation bigrae-config init --backend aws
```

Edit the scaffolded file, then run `doctor` to validate it.

## Root Fields

| Key | Required | Notes |
| --- | --- | --- |
| `version` | no | Defaults to `1`. Only `1` is accepted. |
| `backend` | yes | Must be `aws` or `gcp`. |
| `deployment.name` | yes | Lowercase letters, digits, and internal hyphens. Length: 1-40 characters. |
| `deployment.domain` | yes | Lowercase DNS hostname with at least two labels. IP literals, schemes, trailing dots, and bare hostnames are rejected. |
| `deployment.profile` | no | Defaults to `prod`. Must be allowed by the selected backend. |
| `secrets` | no | Mapping of logical secret name to a reference. Values must be references, not secret values. |
| `settings` | no | Backend-specific mapping. The root schema only checks that this is a mapping. |

Secret names must match `^[a-z][a-z0-9_]*$`.

Secret references must be single-line strings with no surrounding whitespace.
The root schema rejects recognizable raw secret material, including PEM blocks,
multi-line values, and implausibly long values. It cannot distinguish every short
secret value from a reference; `gitleaks` remains part of the enforcement path.

The literal value `prompt` is accepted for any required secret. It records that
the value must be supplied during deployment.

## Validation

Run validation from the repository root:

```bash
uv run --project shifter/installation bigrae-config validate bigrae.yaml
```

The command exits `0` when the config is valid. It exits `1` and prints all
detected issues when validation fails.

Validation rejects:

- missing config files
- invalid YAML
- duplicate YAML mapping keys
- YAML merge keys (`<<`)
- non-mapping top-level YAML
- unknown top-level fields
- unknown `deployment` fields
- missing required fields
- unknown backend names
- unsupported profile/backend combinations
- malformed deployment names or domains
- malformed secret names or references
- missing required backend secrets
- secret names not used by the selected backend

Validation messages are path-based and do not echo rejected input values.

## Doctor

`bigrae-config doctor` validates the selected backend before infrastructure is
applied. Where `validate` checks only the shape of `bigrae.yaml`, `doctor` runs the
checks the selected backend bundle *declares* (required tools on PATH, secret
references, generated-output classification, owned repository paths, and the bundle's
credential-free validation checks) and, opt-in, read-only health probes. It adds no
backend-specific check list of its own; a new backend gets coverage by declaring bundle
metadata.

```bash
# Local-only checks (default): config, tools, secret references, and the backend's
# non-mutating validation checks. No network, no cloud calls.
uv run --project shifter/installation bigrae-config doctor bigrae.yaml

# Also run read-only health probes of the deployment endpoint.
uv run --project shifter/installation bigrae-config doctor bigrae.yaml --checks cloud

# Machine-readable report.
uv run --project shifter/installation bigrae-config doctor bigrae.yaml --json
```

Each check is labelled by side-effect tier:

| Tier | When | Examples |
| --- | --- | --- |
| `local-only` | default | root-config validation, tool lookup, secret references, generated-output classification, owned-path existence, `terraform fmt -check` / `helm template` / `kubectl kustomize` / `kube-linter lint` |
| `cloud-read-only` | opt-in (`--checks cloud`) | read-only HTTP probe of the portal `/health/` endpoint |
| `deployment-mutating` | never run | `terraform apply`, provider/GitHub secret writes, `helm`/`kubectl apply`; reported only, owned by the deploy workflow |

`doctor` is non-mutating by default and exits `1` when any blocking check fails. It never
resolves a secret value; it checks that references are present and well-formed. Reports name
the backend, profile, check names, missing tools, and repo-relative paths only, never config
bodies, secret references or values, or captured command output. `doctor` success is a
pre-mutation readiness signal, not a substitute for the deploy preflight, Terraform, or
runtime health gates.

## Render

`bigrae-config render` projects validated `settings.range_egress` into the selected backend's Terraform bridge variables. Firewall rules come from `bigrae.yaml`, without a second hand-copied allowlist (ADR-017-R4, issue #958).

```bash
# AWS: emits `victim_allowed_cidrs = [...]`
uv run --project shifter/installation bigrae-config render bigrae.yaml \
  --output platform/terraform/environments/<env>/range/victim_allowed_cidrs.auto.tfvars

# GCP: emits `range_egress_mode` + `range_egress_allowed_cidrs`
uv run --project shifter/installation bigrae-config render bigrae.yaml \
  --output /private/staging/range_egress.auto.tfvars
```

The GCP deploy command runs this render itself into its private var files, so a
GCP deploy needs no manual render.

The backend is read from `bigrae.yaml`; the renderer emits the matching bridge
variables. Without `--output` the rendered tfvars is written to stdout. The
command exits `1` and prints the same sanitized issues as `validate` when the
config is invalid. See
[`docs/architecture/range-egress-ip-allowlist.md`](../../docs/architecture/range-egress-ip-allowlist.md)
for the full operator workflow.

## Runtime Inventory

Check the checked-in runtime-env inventory from the repository root:

```bash
uv run --project shifter/installation bigrae-config runtime-inventory --check
```

The runtime-inventory check compares file paths and env-key names only. It
does not print values. It checks committed GCP chart values and rejects committed values for renderer-owned runtime keys. It records the generated renderer key contract. It distinguishes public `bigrae.yaml` installation inputs, the checked-in `.shifter.yaml` operations policy, and gitignored local `.env` files.

## GCP Release Manifest

`bigrae-config gcp-release-manifest` writes one built revision's `bigrae.gcp-release.v1` manifest to standard output. It includes the version, source revision, chart version, and exact `repository@sha256` image identities. Images are `portal`, `provisioner`, `guacd`, `guacamole-client`, and `openvpn`. The release workflow and the CI deploy write it; the GCP deploy
command reads it. The command opens no output file. Use a shell redirect to
write the manifest to a file.

Each `--base-image ROLE=REPOSITORY@sha256:DIGEST` adds the exact guest image
that tenants import for one role (`kali`, `ubuntu`, `dc`). The manifest names
all three roles or none. `--authorization-model-stdin` reads the OpenFGA
authorization model from standard input. The release workflow takes the newest
published guest images and verifies their build provenance before it writes the
manifest (#2668).

```bash
uv run --project shifter/installation bigrae-config gcp-release-manifest \
  --version 1.2.3 --source-revision <40-hex revision> --chart-version <chart version> \
  --image portal=<registry>/portal@sha256:<digest> \
  --image provisioner=<registry>/provisioner@sha256:<digest> \
  --image guacd=<registry>/guacd@sha256:<digest> \
  --image guacamole-client=<registry>/guacamole-client@sha256:<digest> \
  --image openvpn=<registry>/openvpn@sha256:<digest> \
  --base-image kali=<registry>/gce-kali@sha256:<digest> \
  --base-image ubuntu=<registry>/gce-ubuntu@sha256:<digest> \
  --base-image dc=<registry>/gce-dc@sha256:<digest> \
  > release.json
```

## Backend Bundle Contract

`contract.py` defines the machine-readable backend bundle contract.
`registry.py` contains the backend entries consumed by the schema and loader.

A backend bundle declares:

- backend identity and supported profiles
- required command-line tools
- required logical secrets and accepted reference grammar
- generated outputs, including destination and sensitivity
- validation checks and health checks
- cloud-neutral capabilities
- owned repository paths and docs

Generated outputs are classified as `public`, `secret-reference`, or
`secret-value`. A `secret-value` output may only be placed in a Kubernetes Secret
or provider secret store.

Validation commands are stored as argv arrays, not shell strings. Command specs
reject shell metacharacters, absolute paths, path traversal, and tokens with
internal whitespace.

## Published Contract

The versioned JSON contract is committed under `published_contract/`. Backend-bundle authors and tools can use it without reading Shifter internals (issue #1323). `publication.py`
generates the artifact from `contract.py` and `registry.py`; it is never hand-edited.

```bash
# Regenerate the committed artifact from the code.
uv run --project shifter/installation bigrae-config contract export

# Fail on drift, unversioned breaking changes, or non-conformant backends.
uv run --project shifter/installation bigrae-config contract check
```

The `installation` test lane enforces the same three gates: drift (committed artifact
must match the code), breaking change (an incompatible shape change versus the current
version's immutable frozen snapshot `backend-bundle-contract.v<N>.json` requires a
`contract_version` bump and a migration note), and registry conformance (every published
backend record validates against the published JSON schema). See
`published_contract/MIGRATIONS.md` for the procedure to change the contract.

The published JSON schema encodes the contract's security-relevant validators (identifier
grammars, safe `argv` tokens, repository-relative paths, the secret-value destination rule).
To validate a candidate bundle authoritatively, call
`installation.validate_published_bundle(record)`. It runs the schema plus the full
`BackendBundle` contract (including the cross-collection invariants JSON Schema cannot
express), so a bundle it accepts is one the internal contract accepts too.

## Package Layout

| File | Purpose |
| --- | --- |
| `schema.py` | Root config model and root-field validators. |
| `loader.py` | YAML loading, duplicate-key checks, root validation, and backend validation dispatch. |
| `contract.py` | Backend bundle contract types and invariants. |
| `registry.py` | Supported backend bundle registry. |
| `settings_aws.py` | Closed AWS operator settings model and secret-reference grammar. |
| `settings_gcp.py` | Closed GCP operator settings model. |
| `settings_gcp_deploy.py` | Closed GCP deployment-input settings and their runtime and Terraform projections. |
| `gcp_release.py` | GCP release manifest model, parser, and writer. |
| `publication.py` | Generate and check the published, versioned contract artifact. |
| `runtime_inventory.py` | Runtime config surface inventory and env-key drift checker. |
| `runtime_inventory_aws.py` | AWS backend runtime-env key inventories (required, renderer-owned, provisioner-forwarded). |
| `runtime_inventory_gcp.py` | GCP backend runtime-env key inventories. |
| `cli.py` | `bigrae-config init`, `validate`, `doctor`, `render`, `runtime-inventory`, `contract`, and `gcp-release-manifest`. |
| `doctor.py` | Backend-aware `doctor` executor: tier-classified checks over the selected bundle. |
| `scaffold.py` | `init` scaffolding: copy a checked example to a starting `bigrae.yaml`. |
| `render.py` | Render `settings.range_egress` into provider Terraform bridge tfvars. |
| `errors.py` | Sanitized validation issue model. |
| `published_contract/` | Committed contract artifact, frozen per-version snapshots, and migration notes. |
| `examples/` | Valid AWS and GCP example configs. |
