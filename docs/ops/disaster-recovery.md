# Disaster Recovery Runbook—AWS Portal Stack

Tracking issue: <https://github.com/Brad-Edwards/bigrae/issues/160>
Design note: [`docs/architecture/aws-disaster-recovery-preflight-160.md`](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/aws-disaster-recovery-preflight-160.md)
Region: `us-east-2` (all portal resources)

This runbook is the operator procedure for recovering portal data and
infrastructure after a destructive failure (accidental delete, corruption,
region/AZ outage, failed deploy). It covers the AWS portal stack only—RDS,
the portal upload bucket, Cognito, Terraform state and engine/Pulumi state.
AWS runtime recovery uses the shared chart on EKS.
See [EKS operations](portal-eks-operations.md) for cluster and workload recovery.
GCP disaster recovery remains outside this runbook.
For GCP, use [RB014](../runbooks/rb014-database-backup-restore.md) and its stated recovery limits.

Before changes, obtain data-owner and platform-owner approval for the recovery point, maintenance window, and cost.
Use the selected deployment's region, identities, private network, and original Terraform state.
Restores create billable resources.
Keep admission and conflicting writers stopped until domain state and provider inventory agree.
Source checks in #2806 do not requalify the historical recovery exercise.

## How to read this runbook

Three concepts are kept distinct on purpose—conflating them produces a DR plan
that looks complete but cannot restore data:

- **Availability** controls (Multi-AZ, pod replacement, health checks) reduce
  downtime from a *single* failure. They are not a tested restore and do not
  protect against delete/corruption that propagates to the standby.
- **Recoverability** controls (backups, snapshots, object versions, identity
  exports) are what you restore *from*. These are the DR primitives.
- **Evidence** is a dated record that a restore primitive was actually
  exercised and met its target. An untested backup is an assumption, not a
  control. See [Tested recovery exercise](#tested-recovery-exercise).

Data classes drive the target. **Authoritative** state (RDS) must be restorable
with a bounded RPO. **Generated** state (Kubernetes workloads, Redis, range compute)
is rebuilt, not restored. **Ephemeral** state (portal uploads) is accepted-loss
by design. **Identity-provider** state (Cognito) is reseeded, not restored into
the app database. **Infrastructure state** (Terraform/Pulumi) is recovered from
object versions.

## Component recovery matrix

| Component | Data class | Owner surface | RTO | RPO | Restore primitive | Alert source | Region policy |
|---|---|---|---|---|---|---|---|
| Portal RDS (PostgreSQL) | Authoritative | `modules/portal/rds`, env `db_*` vars | ≤ 2 h (drill: ~53 min) | ~5–10 min (PITR log lag) | PITR or snapshot restore to new instance | RDS event subscription (`backup`/`failure`/`low storage`) → backup-alerts SNS | Same-region; Multi-AZ in prod. Cross-region copy deferred (see [Deferred](#deferred-enhancements)) |
| Guacamole database on shared portal RDS | Authoritative (session/connection metadata) | `modules/portal/eks`, Guacamole secret and database settings | ≤ 2 h | ~5–10 min (PITR log lag) | PITR or snapshot restore to new instance | RDS event subscription → backup-alerts SNS | Same-region; Multi-AZ in prod |
| Portal uploads (S3) | Ephemeral | `modules/portal/s3` | n/a | Accepted loss | None—rebuild on re-upload | n/a | Same-region. Versioning/CRR intentionally off (see [S3 uploads](#portal-uploads-s3)) |
| Platform workloads | Generated | `platform/charts/shifter`, EKS root | Requalify after restore | n/a (stateless) | Restore prerequisites, then atomic Helm deployment | Kubernetes readiness and rollout checks | Same-region EKS |
| Cognito user pool | Identity-provider | `modules/portal/cognito` | ≤ 4 h | Best-effort (export cadence) | Terraform recreate pool + reseed users; Django users restore via RDS | Pool deletion protection (prod) | Same-region; managed service |
| Terraform state (S3 backend) | Infrastructure | `scripts/bootstrap/terraform_backend.py`, `render_aws_backend_configs.py` | ≤ 1 h | ≤ last apply | S3 object-version restore; cross-region copy of state bucket | S3 bucket versioning | Same-region; cross-region copy is an operator step |
| Engine/Pulumi state (S3 + DynamoDB) | Infrastructure | `modules/engine-state` | ≤ 1 h | ≤ last stack op | S3 noncurrent-version restore; DynamoDB PITR for locks | DynamoDB PITR | Same-region |
| Secrets Manager | Authoritative (credentials) | Portal and EKS roots, runtime secret references | ≤ 30 min | n/a (regenerated) | Terraform regenerates from `random_password`; rotate consumers | n/a | Same-region |
| Redis (channel layer) | Generated | `modules/portal/redis` | ≤ 30 min | n/a (ephemeral) | Recreate replication group; clients reconnect | Existing Redis alarms | Same-region |
| Range compute/state | Generated | engine provisioner, Pulumi state | ≤ 1 h per range | n/a | Re-provision from scenario template + engine/Pulumi state | Range launch-failure alarm | Same-region |

RTO and RPO are targets, not guarantees.
The 2026-06-24 portal-RDS drill recorded about 53 minutes RTO and 7 minutes RPO on dev.
It checked infrastructure recovery, not application rows, authorization, or current EKS cutover.
Confirm the instance's latest restorable time during an incident; RDS transaction-log shipping bounds the recovery point.
Other rows remain design targets without recorded drills.

## Per-component recovery procedures

### Portal RDS (PostgreSQL)

The portal database is the authoritative application store (Django
`auth_user`, `UserProfile`, audit trail, CMS/CTF/range metadata). Automated
backups are enabled (`backup_retention_days = 7` in all environments),
`copy_tags_to_snapshot = true`, and a final snapshot is taken on delete except
where `db_skip_final_snapshot = true` (dev).

RDS restores never overwrite the source instance—they create a **new**
instance. Recovery is therefore: restore to a new identifier, validate, then
cut over the managed endpoint through a reviewed infrastructure and EKS deployment plan.
Current RDS IAM logins, TLS hostname verification, and Terraform ownership must remain valid.

**Point-in-time recovery (preferred—bounded RPO):**

```sh
# 1. Confirm the window actually available right now.
aws --region us-east-2 rds describe-db-instances \
  --db-instance-identifier <name_prefix>-db \
  --query 'DBInstances[0].LatestRestorableTime'

# 2. Restore to a new instance at the chosen timestamp.
aws --region us-east-2 rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier <name_prefix>-db \
  --target-db-instance-identifier <name_prefix>-db-restore \
  --restore-time 2026-06-24T12:00:00Z \
  --db-subnet-group-name <name_prefix>-db-subnet \
  --no-publicly-accessible

# 3. Wait until available, then validate row counts / latest audit timestamp
#    against the expected pre-incident state before any cutover.
aws --region us-east-2 rds wait db-instance-available \
  --db-instance-identifier <name_prefix>-db-restore
```

**Snapshot restore (when PITR window has aged out):** use
`restore-db-instance-from-db-snapshot` with the latest automated or the final
snapshot (`<name_prefix>-db-final`). Same new-instance-then-cutover flow.

**Cutover:** confirm the restored data, migration level, native SQL users, and effective database duties first. Reconcile the restored database with OpenFGA state, object references, pending operations, queues, and live range inventory. Use a reviewed plan to bind the managed endpoint and deploy the exact approved release.

The EKS renderer obtains endpoint metadata and uses per-workload RDS IAM identities. Changing a legacy secret's `host` alone is not a current EKS cutover. Do not use the retired SSM portal deployment or delete the source instance to force a cutover.

Retain the source for investigation until the data owner approves cleanup. If verification fails, keep traffic and writers stopped and use the approved recovery plan.

### Guacamole RDS (PostgreSQL)

Current EKS uses the portal RDS host with a separate Guacamole database and login.
The EKS renderer reads its endpoint from Terraform outputs.
An instance restore therefore recovers both databases at that recovery point.
Validate each database, its duties, and its consumers separately before cutover.
The earlier standalone Guacamole RDS and secret names apply only to retained historical deployments.
Use their exact source revision and state rather than current EKS assumptions.

### Portal uploads (S3)

Classified **ephemeral** by design—authoritative state lives in RDS, so the
upload bucket has versioning and cross-region replication intentionally disabled
(see [`docs/architecture/s3-bucket-hardening-preflight.md`](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/s3-bucket-hardening-preflight.md)
and #143/#219). There is no restore primitive: lost upload objects are
re-uploaded by users/agents. Do not change this bucket to durable storage to satisfy a generic checklist.
That change affects deletion and retention for agent uploads, experiment scripts, and CTF attachments.
It requires a separate lifecycle, KMS, and ADR decision.

### Platform workloads on EKS

Application state lives in managed databases and object stores. Recreate failed cluster infrastructure through the isolated EKS root. Restore data and secret references before deploying workloads.

Use attested image digests with the normal `eks-deploy` lifecycle. Verify migrations, readiness, workers and authenticated remote access after recovery. Do not use retired EC2 portal scripts for workload recovery.

Follow [EKS operations](portal-eks-operations.md) for deployment checks and rollback limits.

### Cognito

The user pool is Terraform-managed (config recreatable from
`modules/portal/cognito`), but **user identities, MFA enrollment, and group
membership are not in RDS**. Pool deletion protection is on in prod.

- If the pool config is lost but the pool survives: `terraform apply` restores
  configuration (clients, domain, triggers).
- If user *identities* are lost: there is no point-in-time restore. Reseed from
  the last user export (see cadence in [Deferred](#deferred-enhancements)) or
  re-invite. RDS restoration recovers application records.
  Cognito reseeding recovers authentication identities.
  Current native authority also requires matching provider bindings, principals, and OpenFGA state.
  Django flags or restored groups alone do not establish authorization.
  Reconcile these records before enabling sign-in or new range admission.

### Terraform state (S3 backend)

State lives in an S3 backend (`encrypt = true`, `use_lockfile = true`,
`us-east-2`); bucket/key are injected at `init` via `-backend-config`, rendered
by `scripts/bootstrap/terraform_backend.py` /
`scripts/terraform/render_aws_backend_configs.py`. The state bucket has
versioning enabled.

- **Corrupted/deleted state object:** restore the prior S3 object version of the
  specific `…/terraform.tfstate` key (`aws s3api list-object-versions` →
  `copy-object` the good version back over the key). The `use_lockfile` setting
  means no separate DynamoDB lock to reconcile.
- **Region/bucket loss:** copy the versioned state bucket to a recovery bucket
  (`aws s3 sync` or cross-region `copy-object`) and re-`init` with a
  `-backend-config` pointing at the recovery bucket. Keep live backend bucket/key names out of the repository.
  Keep rendered backend files in private `~/.shifter` storage or CI temporary storage.

State may contain generated secret material; treat recovered state files with
the same handling as secrets (no world-readable copies, no CI artifacts).

### Engine / Pulumi state (S3 + DynamoDB)

The engine stores range/stack state in the `<name_prefix>-pulumi-state-<account>`
S3 bucket (versioned, `force_destroy = false`) with a DynamoDB locks table
(`<name_prefix>-pulumi-locks`, PITR enabled) and the `<name_prefix>-pulumi-secrets`
CMK.

- **State object loss:** restore the prior S3 object version (noncurrent
  versions transition to Glacier after the configured window—restore from
  Glacier first if the needed version has aged out).
- **Lock table loss/corruption:** restore via DynamoDB point-in-time recovery to
  a new table, then repoint the engine, or recreate the table (locks are
  transient).
- **Range recovery:** ranges are generated compute. Re-provision from the
  scenario template; the engine reconciles against recovered Pulumi state.

### Secrets Manager

Current EKS runtime database duties use RDS IAM.
Password-backed migration, Guacamole, and application secrets remain separate duties.
The portal data-plane secrets use immediate deletion; EKS-owned Guacamole and OpenFGA secrets use a 30-day recovery window.
Check the exact resource in the selected source revision and state before recovery.

A secret deleted without a recovery window cannot be restored.
Terraform can regenerate it, but database values and consumers must remain consistent.
Refresh affected consumers through the normal EKS deployment.
Never print secret values into logs, argv, state exports, or CI artifacts during recovery.

### Redis (channel layer)

The Django Channels Redis layer is **generated/ephemeral**—no durable state.
Recreate the replication group via Terraform; clients reconnect automatically.
In-flight WebSocket/terminal sessions are lost and re-established by the browser.

## Tested recovery exercise

DR targets are only credible once a real restore has been run end-to-end. The
canonical exercise is an **RDS point-in-time restore-to-new-instance** drill,
which exercises the highest-value authoritative store without touching the live
instance (PITR always restores to a *new* instance).

**Procedure (run against a non-production environment, for example dev):**

1. Note a known-good marker in the source DB (for example latest `audit` row id +
   timestamp) and the current time `T`.
2. Run the PITR command from [Portal RDS](#portal-rds-postgresql) targeting
   `<name_prefix>-db-drill`, restore-time `T`.
3. Record wall-clock from command start to `db-instance-available` → **observed
   RTO**.
4. Connect to the restored instance, confirm the marker row is present and no
   newer-than-`T` rows exist → **observed RPO** (gap between `T` and latest
   restorable time).
5. Delete the drill instance (`delete-db-instance --skip-final-snapshot`) so the
   exercise leaves no billable resource.
6. Fill the evidence log below.

**Evidence log:**

The following table and quotation preserve the 2026-06-24 record.
Revision `5954ab137` retains this record from the original drill change, `c5e4c7579`.
It is historical evidence, not current recovery instructions.
<!-- Exact historical evidence; maintained context remains checked. -->
<!-- vale off -->
<!-- ste-disable -->

| Date | Operator | Component | Restore primitive | Observed RTO | Observed RPO | Result | Artifact |
|---|---|---|---|---|---|---|---|
| 2026-06-24 | Platform operator (dev account) | Portal RDS (dev) `dev-portal-db` | PITR (`--use-latest-restorable-time`) → new `dev-portal-db-drill` (db.t3.medium, single-AZ) | ~53 min to `available` (endpoint live ~3 min in; remainder is the post-restore initial automated backup) | ~7 min (source latest-restorable `02:15:17Z` vs restore decision `02:22:07Z`) | PASS—restored instance reached `available`, engine 16.13 / 100 GB / encrypted matching source, with its own restorable window. Validated at infrastructure level; in-DB row-count validation not performed (private endpoint, no in-VPC session wired for the drill). Drill instance deleted (`--skip-final-snapshot --delete-automated-backups`). | AWS RDS event history for `dev-portal-db-drill`; issue #160 thread |

> Notes from the 2026-06-24 run: observed RTO (~53 min) is comfortably within the
> ≤ 2 h target, but most of it is the initial automated backup RDS takes *after*
> the restore—the instance is connectable far earlier (~3 min). In a real
> incident you can begin validation/cutover before the clean `available` signal.
> Observed RPO (~7 min) reflects normal RDS transaction-log shipping lag (latest
> restorable time trails ~5–7 min behind now); treat the ≤ 5 min PITR target as a
> floor and expect a few minutes of lag in practice.
>
> The drill requires AWS access and creates a temporary billable instance. Re-run
> it periodically (and after major schema/engine changes) and append a new row.

<!-- ste-enable -->
<!-- vale on -->

## Backup-failure monitoring

Backup and snapshot failures surface as **RDS events**, not CloudWatch metrics,
so detection uses an RDS **event subscription** rather than a synthetic metric.
The `modules/portal/backup-alerts` module (wired in every portal env root)
creates:

- a dedicated customer-managed KMS key whose policy grants the
  `events.rds.amazonaws.com` service principal `kms:GenerateDataKey*` +
  `kms:Decrypt` (account-scoped). The shared `aws_sns_topic.alerts` uses AWS-managed `alias/aws/sns`.
  That key cannot grant this principal, so RDS delivery to the shared topic would fail.
- a CMK-encrypted SNS topic `<name_prefix>-db-backup-alerts` with a topic policy
  allowing the RDS event service to publish, and an email subscription gated on
  `alarm_email`.
- one RDS event subscription covering the portal and Guacamole DB instances,
  categories `availability`, `backup`, `failure`, `low storage`, `maintenance`,
  `recovery`.

**To receive alerts:** set a real `alarm_email` in the environment's
`terraform.tfvars` and confirm the SNS email subscription (AWS sends a
confirmation link on first apply). **To verify delivery** without waiting for a
real failure, publish a test message to the topic
(`aws sns publish --topic-arn <topic-arn> --message "DR alert test"`) and confirm
the email arrives.

## Deferred enhancements

These are evaluated and intentionally **not** implemented now, recorded here so
the decision is explicit rather than an unexamined gap.

- **Cross-region RDS automated-backup replication.** Not enabled. When an
  environment needs cross-region RPO, add
  `aws_db_instance_automated_backups_replication` in the destination region
  (requires a second provider alias for that region, a destination KMS key, and
  `source_db_instance_arn` set to the portal instance), and add a
  `replicate_backups_to_region` variable to gate it per environment. Trigger to
  enable: a stated cross-region RTO/RPO requirement for prod.
- **AMI backups for EC2.** Rejected—instances are stateless/generated and
  rebuilt from Terraform + ECR + SSM. Revisit only if a concrete irreplaceable
  host asset appears.
- **S3 uploads versioning / cross-region replication.** Deferred per #143/#219;
  the bucket is ephemeral by design. Enabling CRR requires versioning, which
  changes delete/retention semantics—a separate design decision, not a DR
  toggle.
- **Cognito scheduled user export.** No automated export cadence today; user
  identity reseed is best-effort. Add a scheduled export job if a bounded
  identity RPO becomes a requirement.

## References

- Design note: [`docs/architecture/aws-disaster-recovery-preflight-160.md`](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/aws-disaster-recovery-preflight-160.md)
- S3 hardening decision: [`docs/architecture/s3-bucket-hardening-preflight.md`](https://github.com/OpenRAE/bigrae/blob/dev/docs/architecture/s3-bucket-hardening-preflight.md)
- AWS—encrypted SNS for service events: <https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html>
- AWS—RDS event subscriptions: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_Events.Subscribing.html>
