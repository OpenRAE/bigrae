# ADR-068: The model access broker is parked; keyless-direct is the only live model path

## Status

Accepted 2026-10-05. Supersedes ADR-067 and the parked broker design recorded in
ADR-059, ADR-060, and ADR-061. ADR-064 (keyless-direct default) stays in force.

## Context

The deployment-owned model access broker (ADR-059), its allocation and mandatory
budget accounting (ADR-060), and its operations qualification (ADR-061) are
implemented but not in use. On 2026-10-05:

- The broker and model access are off by default in code.
- The live GCP tenants run no broker and set `MODEL_ACCESS_ENABLED=false`. The
  last tenant that used it moved to keyless access on 2026-10-04.
- No tenant has a broker overlay template or overlay variable.

Range guests reach models through the keyless, predict-only Workload Identity path
(ADR-064).

Three defects make the broker unfit to run:

1. Its TLS certificates are never renewed. The 30-day broker and control
   certificates make every deploy fail once fewer than 14 days remain, and expire
   at day 30. The 365-day signing certificate makes deploys fail once fewer than
   30 days remain.
2. A fresh tenant with a broker template fails its first deploy.
   The trust step runs before Terraform creates the cluster. The local bootstrap path needs
   its trust objects created by hand.
3. Every model call requires finite spend, rate, concurrency, and token limits.
   The schema states that omitting a limit never means unlimited.

ADR-067 kept the broker as an opt-in path, selected a third-party gateway for
optional enforcement, and rejected adding a no-limit mode. That does not match the
intent for model access control. Control was meant to be a capability a
deployment can use, never a requirement. The default is a transparent proxy with
no controls.

## Decision

1. The broker is parked. It is not supported for use, and every deployment keeps
   `settings.model_broker` and `settings.model_access` disabled.
2. Keyless Workload Identity direct access (ADR-064) is the only supported guest
   model path while the broker is parked.
3. No work hardens or extends the parked broker. Changes to its code are limited
   to keeping CI reliable for everyone until it is removed or replaced. Model
   access control is taken up again under the AI Gateway milestone
   ([#2274](https://github.com/Brad-Edwards/bigrae/issues/2274)).
4. Any future model access control path is a transparent proxy by default:
   - Spend, rate, concurrency, token limits, and detections are optional
     controls a deployment can attach. The default is no controls, and a missing
     limit means no limit.
   - Certificates and other credentials renew automatically on established
     practice. A deploy never fails only because a certificate is close to expiry.
   - Enabling it works inside the existing bootstrap and deploy flows with no
     manual steps.

   The intended end state is that guests reach models through that proxy rather
   than keyless-direct. That switch needs its own decision.

## Identity-cutover enforcement

Issue #2321 closes the retained sharing API and composition/selector entry points
before membership reads or publication effects. An enabled runtime setting cannot
override this parked boundary. This enforces the existing decision; it does not
qualify the broker, add publisher authority storage or activate the replacement.
Low-level accounting contracts remain available to their isolated tests.
Keyless-direct and independently supported native source/range controls keep
their existing boundaries. Mounted-route and direct-service tests verify that
legacy operator flags and native credentials both leave sharing unavailable.
The #2909 removal below supersedes this section.

## Removal (#2909)

[Issue #2909](https://github.com/OpenRAE/bigrae/issues/2909) removes the broker and its tests.
The maintainer selected the whole broker subsystem on 2026-11-11.
That includes model-access policy, allocation, accounting, sharing, tenant model sources, CTF model cohorts, and their tables.
It also includes the broker-only authorization actions, settings, deployment resources, and interfaces.
The [removal design](../architecture/model-access/broker-removal-preflight-2909.md) records the boundary and the data migration.

Keyless-direct stays the only guest model path. Removal installs no replacement gateway.
Applied migrations, frozen published snapshots, and Terraform `moved` blocks stay as history.

## Alternatives

| Alternative | Disposition |
| --- | --- |
| Fix the broker now: certificate renewal, bootstrap integration, optional limits | Rejected for now. No tenant uses it, and the work would go into a design planned for replacement. |
| Keep ADR-067 as written | Rejected. Its gateway selection and its rejection of a no-limit mode conflict with the intended default of no controls. |
| Remove the broker code now | Selected by #2909. See the removal section above. |

## Consequences

The broker code, settings, tables, and tests are no longer in the repository.
Model calls from ranges are not metered or limited, consistent with ADR-064.

The [#2274 replacement evaluation](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/model-access/gateway-replacement-evaluation-2274.md)
compares maintained products and records the maintainer's 2026-10-13 selection of self-hosted LiteLLM OSS.
Deployment-owned rotation uses documented key create/delete APIs.
The evaluation defines proposed integration and qualification, including
secure credential delivery and budget continuity. This product selection changes
no runtime or guest model path; the decisions above remain in force.
