# Workspace member invitations

This reference describes the currently bound workspace invitation adapter.
The [original PLAT-235 boundary](https://github.com/OpenRAE/bigrae/blob/dev/docs/_deprecated/architecture/workspace-member-invitations-preflight-1942.md) records the design for issue #1942.
Prepared principal-policy invitation services also exist in the source.
Their acceptance callback is not the adapter currently registered at app startup.

## Stored fields

`WorkspaceInvitation` is a grant made before workspace membership exists.
The `workspaces` domain owns it.

| Field or constraint | Contract |
| --- | --- |
| Recipient | Normalized email address |
| Role | Closed workspace role for the currently bound service; prepared principal-policy rows use an empty role |
| Lifetime | Expiry, acceptance, and revocation fields |
| Generation | Rotating UUID that invalidates earlier credentials |
| Uniqueness | One current invitation per workspace and email, with a conditional case-insensitive constraint |
| Membership creation | Canonical locked membership insertion service |

## Token and login boundary

The email carries a Django timestamp-signed payload in the URL fragment.
The public landing removes the fragment from browser history immediately.
It sends the token to the exact CSRF-protected staging endpoint on the same origin.
Successful staging stores only the invitation UUID and generation in the session.
Raw tokens are not logged, persisted, rendered, or returned by the administration API.

Acceptance occurs within the provider login transaction.
Authentication composition supplies fresh `VerifiedIdentity` evidence through the shared invitation handoff port.
The `user_logged_in` receiver sends the claim through this port to the registered workspace adapter.
An existing Django session must pass provider reauthentication.
The recipient email must match.
Temporary CTF accounts and ambiguous active account matches are refused.

An existing membership is never altered by invitation acceptance.

## Administration boundary

The currently bound administration API accepts browser sessions only.
It requires both `is_staff` and the relevant live workspace operation.
Owner and admin roles can manage member and admin invitations.
An owner grant requires owner authority.
Issue and resend use the shared credential-delivery limiter and email adapter.
Every lifecycle mutation writes strict invitation audit records without recipient PII or signed credentials.

## Delivery status

Delivery follows ADR-071.
Issue and resend commit the invitation and audit first.
An `on_commit` callback makes one bounded `shared.email.attempt_email()` call.
It sends only when the invitation is current and its generation has not changed.
The result updates only the matching generation.
A later resend or revoke prevents an earlier send from updating the current result.

| Field | Meaning |
| --- | --- |
| `delivery_status` | `pending`, `accepted`, `failed`, `unavailable`, or `unknown` |
| `delivery_reason` | Closed transport reason |
| `delivery_observed_at` | Observation time |

`accepted` describes transport acceptance, not delivery to a mailbox.
`unknown` covers rows created before issue #1525.
`unavailable` means no delivering backend is configured and nothing was sent.
Resend is the retry operation.
There is no outbox, retry loop, or thread pool.
See the [email delivery design](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/email-delivery-design-1525.md).

## Source interfaces

- `workspaces/models/_invitation.py`: fields and database constraints.
- `workspaces/invitation_adapter.py`: the registered adapter and the separate prepared policy callback.
- `config/workspace_invitation_auth.py`: authentication composition and transaction handoff.
- `workspaces/api/invitation_views.py`: accepted administration credentials.
- `workspaces/services/_invitations.py`: role-based lifecycle operations.
- `workspaces/services/_invitation_delivery.py`: bounded transport attempt and generation checks.
