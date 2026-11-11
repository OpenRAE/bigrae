# GCP shared-service event capacity contract

Issue #1816 establishes one immutable catalog in
`shifter/installation/capacity_profiles_gcp.py`. A profile ID encodes a version
and participant envelope. The resolver projects that one object into four
consumers:

- Terraform: access-node minimum/maximum, Cloud SQL tier/HA/disk, Redis tier and
  memory, plus the capacity identity label.
- Helm: portal/guacd replica minima, resources, HPAs, and PDBs. It includes one Guacamole client replica, process counts, tunnel ceilings, WebSocket keepalive, termination grace, backend timeout, and connection drain.
- Gate: concurrency, hold and latency budgets, ready guacd minimums, and
  saturation ceilings.
- Drift: an allowlisted desired-state document compared with live provider and
Kubernetes observations. Missing observations fail closed; raw cloud payloads
and secrets are not emitted. Cloud SQL disk capacity is a minimum because storage cannot shrink. Drift accepts a larger retained disk after profile scale-down, but rejects undersized disks.

The installation setting `shared_service_capacity_profile` is the only selector.
Provider, deployment, traffic, and gate profiles remain distinct concepts.
`gcp-deploy` merges the Helm projection into the generated values of every
rollout. The Helm chart is the only GCP renderer (ADR-007, ADR-070). Thus a
release can not keep the profile identity and silently restore the default
workload resources.

The p30 profile sets five portal replicas, two guacd replicas, and one Guacamole client. It provisions regional `db-custom-4-15360` Cloud SQL and 8 GiB Standard HA Redis. Access nodes autoscale from three to eight. Portal and guacd
HPAs may add headroom, but their minimum replicas are sized to carry the gate
without a scale-up race. The Guacamole client remains one replica to preserve
the token-affinity contract from issue #928.

Django retains `CONN_MAX_AGE=0`. The Guacamole/MyBatis JDBC pool has a fixed ten-connection budget. Remaining Cloud SQL connections are reserved for failover and operations. `POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS` is a
Guacamole tunnel-concurrency guard; it is not misrepresented as the JDBC pool.

The strict gate reuses the range functional smoke's Identity Platform/TOTP,
target selection, Guacamole URL parsing, and wire protocol. A successful client
must observe `ready`, acknowledge a post-ready `sync`, and keep parsing the
tunnel for the full hold. Cloud Monitoring supplies restart, CPU, Cloud SQL,
Redis, and external HTTPS load-balancer evidence; bounded `kubectl get` and
`gcloud compute backend-services get-health` reads supply effective readiness
and backend health. No missing signal is converted to zero.

The binding architecture analysis is
[GCP shared-service event capacity preflight](https://github.com/OpenRAE/bigrae/blob/dev/docs/_deprecated/architecture/gcp-shared-service-event-capacity-preflight-1816.md).
The operator procedure is [GCP event capacity profiles](../../ops/gcp-event-capacity.md).
