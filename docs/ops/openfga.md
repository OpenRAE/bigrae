# OpenFGA deployment contract

OpenFGA supplies the policy service after the native identity cutover. Enabling
the Helm values deploys the private server contract; native activation remains
a separate verified step.

## Required preparation

Use a deployment-admin identity, separate from the portal runtime workload, to:

1. provision a dedicated PostgreSQL database and least-privilege database identity;
2. run the OpenFGA datastore migration before server rollout;
3. create the store, render the repository model with `python manage.py render_openfga_model`, publish it, and record the returned immutable model ID;
4. create the runtime preshared key and TLS certificate/CA material in the provider secret store; and
5. set `openfga.storeId`, `openfga.modelId`, database CIDRs, hostname and out-of-band secret/config-map names.

Do not place database URIs, preshared keys or private keys in Helm values. Do not give the portal datastore or model-administration credentials. The application runtime allowlists only check, batch-check, transactional write, exact read and bounded read-changes methods even though OpenFGA preshared authentication does not provide method-level authorization.

## Server posture

The chart pins OpenFGA 1.20.0 by digest, uses a ClusterIP with no ingress, verifies TLS hostnames through the mounted CA, requires preshared authentication, and binds plaintext gRPC to loopback only. Playground and profiler are disabled. NetworkPolicy permits portal-to-OpenFGA and OpenFGA/deployment-admin-to-PostgreSQL traffic only. Resource requests/limits, PostgreSQL pool bounds, readiness/liveness probes, metrics, a disruption budget and two anti-affined replicas are explicit.

The `openfga-admin` service account and its database/DNS egress policy are earlier pre-install/pre-upgrade hook prerequisites for the `openfga-datastore-migrate` hook. They remain available for the job's lifetime and are replaced before the next hook run; the completed job is cleaned up. This also permits first-time enablement on an existing namespace with default-deny policies. The migration must finish before rollout. Store/model publication remains an explicit deployment-admin step because the runtime adapter intentionally has no administration API.

## Rollout and recovery

- Rolling updates use zero surge and at most one unavailable replica. This lets two required-anti-affined replicas upgrade with exactly two eligible nodes while keeping one server available.
- Publish and conformance-test a model before setting its ID in the runtime bundle.
- Treat store and model IDs as immutable release inputs. A missing or malformed ID fails application startup/configuration closed.
- Rotate the runtime preshared key through the external secret store and mounted file. Never put it in an environment variable or release metadata.
- A provider timeout or server error denies checks. A failed policy write becomes `unresolved`; status `GET` requests are observational, while the explicit CSRF-protected reconciliation `POST` checks its exact generation-bound tuple state before a conflicting edit is allowed. Replaying a generation is append-only and idempotent; a superseded generation cannot restore access.
- Prepare the platform's locked environment with `uv sync --frozen` from `shifter/shifter_platform`, then run `scripts/run_openfga_integration.sh` there to reproduce the released-server PostgreSQL/TLS/auth conformance suite locally. The harness uses the prepared environment without resolving dependencies or building packages during execution.
- The opt-in `platform/charts/shifter/tests/test_openfga_rollout.py` exercises a real two-worker scheduler upgrade. Create a disposable kind cluster named `shifter-2315-rollout` with one control-plane and two workers, then run the test with `OPENFGA_ROLLOUT_KUBECONFIG` pointing at that cluster's dedicated kubeconfig. It retains the rendered placement and rollout settings and runs the pinned server with in-memory storage and no exposed Service; it is a scheduling test, not a replacement for the PostgreSQL/TLS suite.

## Replace retained TLS certificates

Strict TLS clients reject issued certificates without an Authority Key
Identifier and CA certificates without a Subject Key Identifier. Check both
server certificates with `openssl verify -x509_strict -CAfile ca.crt server.crt`.
The current GCP `generate_policy_bundles` generator includes these extensions;
an existing secret is retained by deployment and is not regenerated automatically.

Use the existing provider secret bundles and Kubernetes projections for a
certificate replacement. Record the current secret version IDs for recovery.
Keep the runtime and admin authentication keys, store ID and model ID unchanged.
Transfer bundle payloads through process input, never command arguments or logs.

1. Generate and strictly verify the replacement CA and server certificates.
2. Publish a CA trust bundle containing the old and new public CAs. Synchronize
   it through `sync_openfga_secrets.py`, restart policy clients and verify that
   their mounted trust files contain both CAs before changing either server.
3. Add new runtime and admin secret versions with the replacement TLS material
   and the existing authentication keys. Synchronize the bundles, then roll
   `openfga` and `openfga-admin` and wait for both Deployments to become ready.
4. Run the normal deployment. Require the publisher's verified HTTPS connection,
   native identity activation, workload readiness and running-image checks.
5. Publish the new CA alone, synchronize it, restart policy clients and verify
   native identity readiness again. Retain previous secret versions for recovery.

Keep both CAs trusted until every server and client has completed the change.
On failure, retain that trust bundle while restoring the recorded server bundle
versions and restarting affected servers. Never disable certificate or hostname
verification to complete publication.
