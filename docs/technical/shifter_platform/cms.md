# BigRAE CMS

Reference for content registration, assets, and range intent.

## Responsibility

- Scenario catalog (declarative templates)
- Asset management (agents, credentials)
- Range content tracking (scenario associations)
- Validated range inputs for Engine

CMS owns **what** gets deployed. Engine owns **how** it gets provisioned.

## Architecture

CMS owns registered content and desired range state.
Engine owns resource generations, dispatch, and accepted results.
Mission Control calls CMS services; external adapters use the independent SDK.
See [lifecycle contracts](identity-lifecycle-contracts.md) for the data flows and trust boundaries.

## Scenario Templates

Current scenarios are registered RAES environment packs.
The retired `cms/scenarios/templates/` format is not a supported authoring interface.
Use [the scenario contract reference](../handbook/scenario-contract-transition.md) for versions and compatibility.

### Template Schema

The pinned RAES distribution owns authored SDL and compiled plans.
`shared.raes` adapts that contract; CMS validates packs through `raes-env-packs`.
Do not create a second local schema or rename retired payload keys to imply migration.

### Available Scenarios

The catalog is a scoped projection of registered sources and admitted capabilities.
Use the scenario list and detail APIs for the current caller's visible catalog.
The [public pack collection](https://github.com/OpenRAE/bigrae/blob/dev/shifter/environment-packs/README.md) identifies the shipped smoke examples.
A source directory alone does not establish registration or launchability.

## Hydrated Range Config

CMS verifies source identity, resolves current authority, and compiles admitted RAES intent.
Immutable operation inputs retain plan, artifact, access, and adapter bindings.
Those bindings are facts, not permission grants.
The provisioner consumes serialized data through its independent reader.
It does not load application models or execute pack code in the portal.

## Models

### Catalog Models (System-Defined Types)

| Model | Purpose |
|-------|---------|
| `OperatingSystem` | Available OS types (Windows, Ubuntu, Kali) |
| `CredentialType` | Types of credentials (SCM, Deployment Profile) |
| `InstanceType` | VM instance type definitions |
| `AppType` | Application type definitions (NGFW) |

### Asset Models (User-Owned)

| Model | Purpose |
|-------|---------|
| `AgentConfig` | XDR/XSIAM agent installer uploaded by user |
| `Credential` | User credentials with type-specific data |

### Entity Models (Materialized in Ranges)

| Model | Purpose |
|-------|---------|
| `Instance` | VM instance definition in a range |
| `App` | Application (NGFW) definition in a range |
| `Subnet` | Network subnet definition in a range |

### Request Tracking

| Model | Purpose |
|-------|---------|
| `Request` | Provisioning request container (correlation UUID) |
| `RangeInstance` | Tracks hydrated scenario config sent to Engine |
| `MissionControlTenantLeasePolicy` | Optional complete runtime replacement for the deployment lease fallback |
| `MissionControlGroupLeasePolicy` | One complete, revisioned lease policy for an eligible Django RBAC group |
| `MissionControl*LeasePolicyRevision` | Durable tenant/group compare-and-set fences retained across policy reset |

### Mission Control lease-policy boundary

CMS owns runtime Mission Control lease-policy persistence and resolution. The
canonical value type remains
`shared.mission_control_lease.MissionControlLeasePolicy`; ORM columns and API
serializers only adapt that contract at their boundaries.

`cms.services.resolve_mission_control_lease_policy()` reads the effective tenant
policy and committed eligible-group memberships. Multiple configured groups use minimum durations and logical-AND extension admission.
The tenant maximum bounds the result. The resolver never reads provider claim copies,
workspace/organization roles, CTF teams, or caller-supplied group selectors.

Cold creation and warm claim resolve and snapshot the initial, increment,
maximum, source, tenant revision, and group revisions inside their existing
assignment transaction. Engine and provider adapters receive only the persisted
deadline effects and do not query policy. Extension admission re-resolves the
live boolean switch, while the generation's duration fields remain immutable.

The `/api/v1/administer/mission-control/lease-policy/` surface requires current `installation.manage_lease_policy` authority.
It accepts native credentials; browser sessions also require CSRF.
Commands replace or reset a complete policy with revision compare-and-set checks.
Strict audit commits in the mutation transaction.
A staff or superuser flag alone grants no authority. Reset advances a durable scope revision before removing the
override, preventing a stale command from matching a later policy incarnation.

## Internal Modules

These modules implement the owning service; they are not external integration APIs.

| Module | Purpose |
| --- | --- |
| `cms/scenarios/pack_validation.py` | Released environment-pack validation and digest checks |
| `cms/services/_content_ingestion.py` | Native registration, custody, and audit |
| `cms/services/_scoped_range_launch.py` | Native launch admission and dispatch |
| `cms/services/_scoped_uploads.py` | Scoped installer admission and finalization |

## Service Interface

These are abbreviated service signatures.
Native entrypoints require a current `CredentialContext` and the applicable explicit content scope.
Use `cms/services/__init__.py` and each exported function for complete typed arguments.
A parameter named `user` does not permit a bare Django user to replace native proof.

### Agents

| Function | Purpose |
|----------|---------|
| `create_agent(user, ...)` | Create agent record |
| `delete_agent(user, agent_id)` | Soft delete agent |
| `list_agents(user)` | Get user's agents |
| `get_agent(user, agent_id)` | Get single agent |

### Credentials

| Function | Purpose |
|----------|---------|
| `create_credential(user, credential_type_slug, ...)` | Create credential (scm, authcode) |
| `delete_credential(user, credential_id)` | Delete credential |
| `list_credentials(user)` | Get user's credentials (includes type) |
| `get_credential(user, credential_id)` | Get single credential |

### Ranges

| Function | Purpose |
|----------|---------|
| `create_range(...)` | Admit scoped RAES intent and call Engine |
| `destroy_range(user, range_id)` | Tear down range |
| `list_ranges(user)` | Get user's ranges |
| `get_range(user, range_id)` | Get single range |
| `cancel_range(user, range_id)` | Cancel provisioning range |
| `pause_range(user, range_id)` | Pause range |
| `resume_range(user, range_id)` | Resume range |

### Uploads

| Function | Purpose |
|----------|---------|
| `initiate_upload(user, name, filename, file_size)` | Validate, generate presigned URL |
| `complete_upload(user, upload_token)` | Verify and finalize upload |
| `cancel_upload(user, upload_token)` | Clean up failed upload |

Agent upload cancel is an authenticated state-changing POST.
Browser sessions require CSRF validation.
The explicit JSON request uses `X-CSRFToken`.
Page-unload cleanup can use a form-encoded `sendBeacon()` body with `upload_token` and `csrfmiddlewaretoken`.

`cancel_upload` verifies the signed token against retained `AgentUpload` custody and current scope authority.
An expired signed token can identify cleanup; it does not authorize upload finalization.
Malformed tokens or mismatched identity, asset kind, and staging key fail without storage effects.
Cancellation records `cancelled` and strict audit under the upload and budget locks.
The existing cleanup worker removes exact recorded objects after URL expiry.
Uncertain cleanup retains custody and its budget reservation.

Per-file size limit. A single agent installer may be at most
`AGENT_MAX_FILE_SIZE_MB` (default 2048, that is 2 GiB using binary MiB). This
per-file ceiling is distinct from the per-user storage quota below.

One policy helper, `cms.assets.validation.agent_max_file_size_bytes`, supplies the per-file ceiling.
The SPA checks the selected file before initiation.
`initiate_upload` checks declared size before quota reservation or URL issuance.
The presigned PUT binds that declared length.

`complete_upload` requires provider-reported length to equal the retained declared size.
It also applies the current size limit before catalog admission.
An oversized or mismatched object is refused; retained cleanup removes only its recorded objects.
Header inspection and copying bind to the observed provider object identity.
The SPA reads `max_file_size_bytes` from the agent-list response.

### User Quota

| Function | Purpose |
|----------|---------|
| `get_storage_used(user)` | Check storage quota |

`AGENT_USER_STORAGE_QUOTA_MB` defaults to 5120 MiB (5 GiB).
Despite its retained name, native upload accounting applies it to the exact content scope.
The budget includes installed agents, retained named files, and pending cleanup reservations.
The scope budget lock serializes admission.

This aggregate limit is separate from the per-file ceiling.
A request can satisfy one limit and exceed the other.
The per-file check runs before the aggregate quota check.
Cancellation does not release uncertain cleanup reservations.

### Scenarios

| Function | Purpose |
|----------|---------|
| `list_scenarios(user)` | Get available scenarios with metadata |
| `get_scenario(...)` | Get a visible registered scenario |
| `validate_scenario_requirements(...)` | Check selected scenario requirements |
