# User lifecycle administration (technical)

Reference for account states, lifecycle commands, reset, and ownership transfer.

This note describes the implementation of user lifecycle administration
(PLAT-236, issue #1943): account state transitions, administrator-triggered
password reset, and bounded ownership transfer. It is constrained by PLAT-241
(cloud-agnostic, proven components) and the architecture preflight at
`docs/_deprecated/architecture/user-lifecycle-administration-preflight-1943.md`.

## Account state model

`User.is_active` remains the single authentication-enforcement bit. The only
added persisted fact is `UserProfile.suspended_at` (a nullable timestamp).
The administrator-facing state is *derived*, never stored as a second enum that
could disagree with `is_active`:

| Derived state | Durable facts |
| --- | --- |
| active | `is_active=True`, no suspension, not deleted |
| suspended | `is_active=False`, `suspended_at` set, not deleted |
| deactivated | `is_active=False`, no suspension, not deleted |
| deleted | profile `deleted_at` set (also forces `is_active=False`) |

`management.lifecycle` owns the state machine:

- `derive_lifecycle_state(user)` computes the state from durable facts.
- `available_actions(user, actor)` returns the server-derived, authority-aware
  action hints the detail projection exposes.
- `transition_account(user, *, action, actor, audit)` is the one command for the
  closed action set (`activate`, `deactivate`, `suspend`, `delete`). It locks the user and profile rows, derives current state, and validates the closed transition table. It updates `is_active` and `suspended_at` together and revokes live API tokens for disabling actions. A strict request-attributed audit event commits in the same transaction. Repeating the current
  state is an idempotent no-op that writes no audit and claims no transition.

Locked guards prohibit self-disable and removal of the last active superuser.
Native callers need current installation policy.
The retained legacy user branch also restricts superuser-target changes.

## Authentication enforcement

Deactivated, suspended, and soft-deleted accounts all hold `is_active=False`, so
every authentication path converges on that one bit:

- `config.oidc.ShifterOIDCBackend` and `config.identity_platform.IdentityPlatformBackend` reject inactive accounts in both `get_user` and `authenticate`. Existing provider sessions cannot reload; claims synchronization cannot reactivate a blocked account.
- `shared.api_tokens.authentication.ApiTokenAuthentication` rejects a token whose
  owner is missing, inactive, or soft-deleted, on top of the token revocation the
  transition already performs.
- The local and CTF backends and the DRF permission and actor-resolution seams
  already gate `is_active`.

`management.services.mark_user_deleted` now also clears `is_active` so soft
deletion blocks authentication; migration
`management/migrations/0012_disable_soft_deleted_accounts.py` converges any
pre-existing soft-deleted accounts.

## Password reset

`management.password_reset` is an account-origin-aware dispatcher whose first
implementation is Django's local password reset. `reset_eligibility(user)` admits
only an active, local, non-CTF account with a usable password and a valid email.
`request_password_reset` uses the shared `shared.credential_delivery` budget and validated public origin from `shared.site_url`.

It records strict secret-free audit and sends Django's `PasswordResetForm` email on transaction commit. It refuses with `reset_delivery_unavailable` before the audit when
`EMAIL_DELIVERY_AVAILABLE` is false. The form sends through one bounded
`shared.email.attempt_email()` call (ADR-071).

A non-accepted send raises
`reset_delivery_failed`, which the API returns as 503; the request and its audit
stay committed. `config.password_reset_views` mounts Django's reset-confirm and complete landing pages. The confirm view records strict audit after a completed password change.

## Ownership transfer

The mounted composition-root view is `PolicyAdministerTransferOwnershipView`.
It requires current `installation.manage_principals` authority and a matching credential ceiling.
Staff, superuser, and `auth.change_user` values do not independently authorize transfer.
The view delegates to `cms.services.policy_transfer_user_ownership`.
CMS composes Workspaces and Engine through their public service facades.
Each transfer preserves the expected departing owner and rechecks current resource custody.

The manifest is a closed set of resource kinds; there is no wildcard, generic
`owner_id` rewrite, or reflective scan:

- **Ranges** use `cms.services.policy_reassign_range_owner` for each selected range.
  The service preserves CMS/Engine custody, expected departing owner, active-range uniqueness, and live-VPN refusal.
- **Workspaces** use `workspaces.services.admin_transfer_workspace_principal` for each eligible ownership candidate.
  Current policy, destination membership, expected owner, last-owner, and archive checks remain mandatory.

Workspace transfers precede range transfers.
Each successful resource transfer commits independently with strict audit.
Blocked resources retain bounded counts; offboarding is not one globally atomic transaction.
An intervening owner change blocks that resource without undoing earlier successful transfers.

## API surface

All routes extend `/api/v1/administer/users/`:

- `POST .../<pk>/lifecycle/` (`installation.manage_principals`): activate, deactivate, suspend.
- `POST .../<pk>/reset-password/` (`installation.manage_principals`): trigger a Django reset.
- `POST .../<pk>/transfer-ownership/` (`installation.manage_principals`): the offboarding
  transfer, served at the composition root.
- `POST .../<pk>/set-active/` and `POST .../<pk>/delete/` remain as v1
  compatibility adapters that delegate to the one transition service.

The detail projection adds server-derived `lifecycle_state` and
`available_actions`. The SPA (`frontend/src/features/administer/UserDetailPage.tsx`)
renders the actions and reports transfer results; it never reconstructs the
transition or reset-eligibility policy, and every endpoint reauthorizes.
