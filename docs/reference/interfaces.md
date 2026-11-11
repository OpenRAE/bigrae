# Supported interfaces

This reference maps supported interfaces to their maintained sources and detailed documentation.
Source paths below are relative to `shifter/shifter_platform/`, unless stated otherwise.
The installed release determines the applicable dependency versions.

## HTTP API

The authenticated API uses `/api/v1/`.
`config/urls.py` and `config/api_urls.py` define mounted paths and include order.
`config.account_admin_urls` mounts native administration before other domain routes.
An unmounted controller is not a supported endpoint.

| Interface family | Authoritative source | Detailed reference |
| --- | --- | --- |
| Accounts, organizations, workspaces, policy, memberships, ownership, invitations, quota, and egress | `workspaces/api/account_admin_urls.py` and its controllers | [Account administration](../technical/shifter_platform/account-administration.md), [console](../technical/shifter_platform/org-workspace-admin-console.md) |
| Users, personal credentials, service admissions, and audit | `management/api/account_admin_urls.py`, `credential_urls.py` | [Credentials](../technical/shifter_platform/access-credentials.md), [user lifecycle](../technical/shifter_platform/user-lifecycle-administration.md), [audit](../technical/shifter_platform/admin-audit-activity.md) |
| Content, image inventory, adapters, preparation, and pack files | `cms/api/urls.py`, `cms/api/account_admin_urls.py` | [CMS](../technical/shifter_platform/cms.md), [content authority](../technical/shifter_platform/content-range-authority.md) |
| CTF events, participants, challenges, scoring, communications, and receipts | `ctf/api/urls.py`, `ctf/api/operation_policy.py` | [CTF](../technical/shifter_platform/ctf.md), [communications](../technical/shifter_platform/ctf-communications.md) |
| Range launch, status, lifecycle, uploads, remote access, and VPN delivery | `mission_control/api/urls.py` | [API conventions](../technical/dev/api.md), [Mission Control](../technical/shifter_platform/mission_control.md) |
| Bootstrap, dashboard, schema, and Swagger UI | `config/api_urls.py` | [API development](../technical/dev/api.md) |

`/api/v1/schema/` serves OpenAPI; `/api/v1/docs/` serves the local Swagger UI.
Both require a current native session or admitted bearer credential.
The committed contract is `openapi/v1.json`; its consumer is `frontend/src/api/schema.d.ts`.
Views, serializers, schema extensions, and their docstrings supply its maintained text.
No separate hand-written field schema exists here.

Regenerate or check the existing contract from the platform directory:

```shell
TESTING=1 TEST_DB_BACKEND=sqlite uv run python manage.py api_contract --check
```

Use `npm --prefix frontend run gen:api` when an intended source change requires regeneration.
The separate `openapi/account-admin-prepared.json` artifact uses `config.account_admin_urls` as its URLConf.
It does not add a second production route set.

Native action ceilings restrict authority; they do not grant an operation.
Services also check live policy, SQL ancestry, custody, and lifecycle.
Session mutations retain CSRF validation. Invalid bearer proof fails before session fallback.
Read [API errors and pagination](../technical/dev/api.md#errors) before writing a client.
Some retained endpoints return a documented legacy error body; inspect each operation's declared response.

## WebSocket API

| Route | Source | Purpose |
| --- | --- | --- |
| `ws/terminal/<instance_uuid>/` | `mission_control/routing.py` | Authorized guest terminal |
| `ws/range-status/<request_id>/` | `mission_control/routing.py` | Exact range-request status |
| `ws/ngfw-status/<app_id>/` | `mission_control/routing.py` | Device status |
| `/ws/notifications/` | `shared/routing.py` | Authorized topic notifications and refresh hints |

See [Mission Control](../technical/shifter_platform/mission_control.md) for close codes and continuing checks.
Notifications are projections, not authoritative lifecycle state.

## Adapter SDK

The repository package is `shifter/shifter_adapter_sdk/`.
Its distribution name is `bigrae-adapter-sdk`.
Canonical imports use `bigrae_adapter_sdk`; legacy `shifter_adapter_sdk` imports share the contract classes.
Distribution, plugin protocol, verification API, and report versions are separate identities.

| Public module | Supported surface |
| --- | --- |
| `bigrae_adapter_sdk` | SDK `__version__` |
| `runtime` | `PluginManifest`, inspection input/result, file input, runtime input/plan, guest targets/actions/references, provisioning and secret values, plugin protocol |
| `runtime` functions | `decode_message`, `canonical_digest`, `parse_input`, `parse_result`, `read_file_input` |
| `preparation` | Closed input, build, output, cleanup evidence and `PreparationWorkerResult` |
| `trial` | `TrialInput`, `TrialStatus`, `TrialExport`, `parse_trial_output`, fixed paths and output limit |
| `guest` | `read_runtime_values` and bounded runtime-value transport |
| `verification` | Public declarations, runner, bindings, outcomes, discovery, execution, redacted report, and exit status |
| `worker` | Standard module entrypoint for isolated inspection and runtime planning |

The SDK's typed models and validators define exact fields, bounds, and cross-field conditions.
They are maintained source reference; generated per-symbol HTML pages are not available.
The [SDK README](https://github.com/OpenRAE/bigrae/blob/dev/shifter/shifter_adapter_sdk/README.md) explains runtime, preparation, files, guest access, and trials.
The [verification guide](../technical/shifter_platform/scenario-verification.md) lists every public verification export and gives integration steps.

Runtime plugins declare one exact installed distribution, version, entry point, and image digest.
Administrators bind executable software separately from content installation.
The isolated worker plans bounded actions; the host authorizes and executes them.
Compatibility inspection alone does not establish guest readiness.

Keyless-direct is the only guest model path (ADR-064).
Operator verification plugins use a separate runner contract and do not replace the runtime worker.
Signed-receipt validators use a third, separate callback protocol.

Local wheels support independent development.
A local wheel, workflow, or importable module does not establish registry publication.
SDK release and distribution decisions remain in [issue #2241](https://github.com/OpenRAE/bigrae/issues/2241).

## Commands

Run command help from `shifter/shifter_platform/` in the configured environment:

```shell
uv run python manage.py help register_pack
uv run python manage.py help experiment_batch
uv run python manage.py help api_contract
```

| Command | Maintained parser | Contract |
| --- | --- | --- |
| `register_pack` | `cms/management/commands/register_pack.py` | Exact package identity, native credential file, and explicit scope |
| `validate_pack_conformance` | `cms/management/commands/validate_pack_conformance.py` | Trusted conformance of a registered source |
| `bootstrap_inbox_catalog` | `cms/management/commands/bootstrap_inbox_catalog.py` | Uniform registration of declared shipped packs |
| `experiment_batch` | `cms/management/commands/experiment_batch.py` | `admit`, `show`, or `export`; organization and credential file required |
| `qualify_disposable_workers` | `engine/management/commands/qualify_disposable_workers.py` | Explicit operator qualification of disposable workers |
| `render_openfga_model` | `shared/management/commands/render_openfga_model.py` | Render the pinned model; no runtime model publication |
| `api_contract` | `config/management/commands/api_contract.py` | Generate, check drift, or compare compatibility |

Command help supplies current flags and defaults; the owning service still authorizes effects.
Use private credential files where the parser requires them.
Never place bearer proof in argv, examples, shell history, or logs.
The verification SDK supplies no built-in scenario CLI or concrete runner.

## Scenario and schema contracts

| Contract | Maintained authority | Documentation |
| --- | --- | --- |
| Authored SDL, experiment inputs, and environment-pack identity | Pinned `raes` and `raes-env-packs`; `shared/raes` adapters | [Scenario transition](../technical/handbook/scenario-contract-transition.md) |
| Backend demand, supply, and realization limits | `shared/raes/backend-manifest.json`, `backend-realization-envelope.json` and their builders | [Registered projects](../technical/shifter_platform/registered-gcp-range-projects.md), [experiment admission](../technical/shifter_platform/experiment-admission.md) |
| Native operation inputs and results | `shared/operation_envelope.py`, `shared/raes/operation_input.py`, independent provisioner reader | [Lifecycle contracts](../technical/shifter_platform/identity-lifecycle-contracts.md) |
| CTF reference catalog and content bundle | `shared/schemas/ctf_content_reference.py`, `ctf/content_bundle.py` | [Publish scenario content](../dev/ctf-scenario-content.md) |
| Signed-receipt verification | `shared/receipt_validation.py`, `ctf/validators` and Engine registration | [Receipt contract](../dev/ctf-signed-receipt-validators.md) |
| Public example packs | `shifter/environment-packs/`, portal Dockerfile, inbox manifest | [Collection reference](https://github.com/OpenRAE/bigrae/blob/dev/shifter/environment-packs/README.md) |
| Synthetic experiment fixture | `tests/shared/raes/fixtures/experiment-admission/README.md` and adjacent license | [Experiment admission](../technical/shifter_platform/experiment-admission.md) |

Authoring acceptance does not establish backend support.
Advertised capability does not establish observed guest effects or live qualification.
The referenced pages state remaining qualification limits.
Digest-bound pack documents, fixtures, and generated schemas remain exact records.
