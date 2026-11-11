# RB023: GitHub-less GCP deploy, update, or teardown failed

Applicability: GCP deployments that use the GitHub-less deploy path (ADR-070).
Operator: platform owner. Verified against the repository: 2026-11-02.

The procedures are in the
[GitHub-less GCP deployment guide](../technical/handbook/gcp-github-less-deployment.md).
This runbook covers a failed `gcp-deploy`, `gcp-release-scan`, `gcp-smoke`,
`gcp-destroy`, or `gcp-cmek-migrate` run, and a bucket key failure in
`gcp-foundation`. A CI deployment runs the same commands. Its job log shows the
same messages.

Use the [shared operating contract](index.md#shared-operating-contract) before investigation or recovery.

## Symptom

A lifecycle command stops with a status other than 0:

| Exit status | Meaning |
| --- | --- |
| 1 | A stage failed. The command printed the reason and removed its lock. |
| 2 | The command arguments are not valid. |
| 3 | The deployment is current, but the advisory smoke failed. The command printed `The post-deploy smoke failed; the deployment itself completed`. |

Before each step, the command prints `Running:` and the redacted command line.
A failed step prints `<tool> <subcommand> failed with exit status <n>`. These
messages identify the stage:

| Stage | Messages |
| --- | --- |
| Inputs | `required tools are missing from PATH`; `deployment inputs must include bigrae.yaml`; `deployment inputs must include terraform.tfvars or terraform.tfvars.json`; `range-images.json role ... must be projects/<project>/global/images/[family/]<name>`; `the deploy tooling revision does not match the release revision`; `the deploy tooling has local changes`; `--allow-unreleased-tooling requires settings.deployment_tier: test`; `a release manifest is required`; `settings.release_trust is required to verify release provenance`; `derived ... identity ... is not a valid service account` |
| Lock | `the deployment lock is held by <command> run <run id> (started <time>)` |
| Infrastructure | `settings.operator_bootstrap is required`; `settings.operator_bootstrap.admin_password_secret_ref is required`; `the operator password secret has an empty latest version`; `cannot read the operator password from Secret Manager`; `GCP operator email must use the ... domain`; `terraform apply failed with exit status <n>` |
| Preconditions | `Required GCE range-cell input ... is not set`; `Range guest image not imported`; `Range guest image check failed` |
| Images | `cannot import release image ...`; `imported image ... resolved to a different digest` |
| Scan | `exact-release scan failed; the rollout is blocked`; `failed to store the redacted release verdict` |
| Verify | `no attestation is stored with ...`; `no attestation of ... satisfies the release trust policy` |
| Rollout | `... belongs to another Helm release; refusing to adopt it`; `running workloads do not match the approved release`; `ingress platform-external did not receive a load-balancer address within 10 minutes`; `certificate platform-managed-cert did not appear for ... within 2 minutes`; `certificate platform-managed-cert is not Active for ... after 60 minutes`; `OpenVPN pool servers did not all report healthy within 10 minutes` |
| Identity | `Legacy identity conversion requires both private facts files`; `Identity status probe was inconclusive; workloads remain unchanged`; `A fresh install needs settings.operator_bootstrap`; `kubectl wait` fails on job `identity-cutover-status-*` or `identity-cutover-*` |
| Policy | `Only some OpenFGA secrets exist`; `This release has no authorization model`; `The OpenFGA publisher returned no binding`; `kubectl wait` fails on job `openfga-publish-*` |
| Catalog | The deploy completes, then warns `The in-box catalog may be incomplete` or `Automatic catalog registration did not complete`. The application is active. |
| Teardown | `--confirm must equal the deployment name`; `terraform destroy failed after 6 attempts` |
| Bucket keys | `Bucket <bucket> default key is not <key>; apply its owner root first`; `Bucket <bucket>: <n> live objects do not use <key> after the rewrite`; `storage_cmek_buckets must map each bucket name to its key`; `Permission denied on Cloud KMS key` in a Terraform, upload, or download error |

The warning `<bucket>: objects that do not use the bucket key` is not a failure.
It counts the noncurrent, soft-deleted, retention-locked, and wildcard-named
objects that keep the Google-managed key.

An OpenFGA publisher error about a missing Authority Key Identifier or Subject
Key Identifier means that retained TLS material fails strict verification.
Deployment preserves existing secret bundles. Follow the
[certificate replacement procedure](../ops/openfga.md#replace-retained-tls-certificates),
including live server checks and removal of the old CA after client migration.
Keep certificate and hostname verification enabled.

## Investigation

Record the command, the deployment name, the release revision, and the last
`Running:` line. Run the checks through the deployer image of the release, as
the guide describes, or from a clean checkout of the release revision.

A test cycle can run for several hours. The gcloud user credentials and the
Application Default Credentials (ADC) can expire during that time. Then the
next gcloud call fails with `Reauthentication failed. cannot prompt during
non-interactive execution`. Before each deploy or destroy, check both
credentials:

```bash
CLOUDSDK_CORE_ACCOUNT=<operator> gcloud auth print-access-token > /dev/null
gcloud auth application-default print-access-token > /dev/null
```

1. Check the tools and the bundle. The preflight renders the Terraform values
   and makes no change.

   Read-only command:

   ```bash
   ./scripts/bootstrap/deploy.py preflight --cloud gcp --env <environment> --store gs://<bucket>
   ./scripts/bootstrap/deploy.py gcp-config show --store gs://<bucket>
   ```

2. For a held lock, read the holder. Find out if that command still runs, for
   example in a CI run or in the shell of another operator.

   Read-only command:

   ```bash
   gcloud storage cat gs://<bucket>/locks/deploy.lock
   ```

3. For a Terraform failure, look for a Terraform state lock. A `default.tflock`
   object under the prefix is a lock that a stopped apply can leave.

   Read-only command:

   ```bash
   gcloud storage ls gs://<project>-terraform-state/shifter/<environment>/platform-core/
   ```

4. For an input failure, check the operator password versions and the range
   images. Do not read a secret value.

   Read-only command:

   ```bash
   gcloud secrets versions list <operator-password-secret> --project <project>
   gcloud compute images describe <image> --project <range-project>
   ```

5. For a scan, verify, or running-image failure, read the evidence. The deploy
   identity can read the release-evidence bucket. Use the newest run ID under
   the revision.

   Read-only command:

   ```bash
   gcloud storage ls --impersonate-service-account=<deploy-identity> \
     gs://<project>-release-evidence/release-scans/<revision>/
   gcloud storage ls --impersonate-service-account=<deploy-identity> \
     gs://<project>-release-evidence/deployments/<revision>/
   gcloud storage cat --impersonate-service-account=<deploy-identity> \
     gs://<project>-release-evidence/release-scans/<revision>/<run-id>/<attempt>/verdict.json
   ```

6. For a rollout failure, read the cluster state through Connect Gateway as the
   deploy identity. Use a separate `KUBECONFIG`, and unset both variables when
   you finish. The deploy command uses its own private `KUBECONFIG`, so your
   kubeconfig contexts do not change its context.
   `gcloud container clusters get-credentials` writes the private control-plane
   endpoint, which the workstation cannot reach when
   `gke_master_authorized_cidrs = []`. Use the fleet membership credentials instead.

   Read-only command:

   ```bash
   export CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT=<deploy-identity>
   export KUBECONFIG=/tmp/<environment>-check
   gcloud container fleet memberships get-credentials shifter-<environment>-gke \
     --location <region> --project <project>
   helm -n shifter-system status shifter
   helm -n shifter-system history shifter
   kubectl -n shifter-platform get deploy,pods
   kubectl -n shifter-platform rollout status deploy/<deployment> --timeout=60s
   kubectl -n shifter-platform get events --sort-by=.lastTimestamp
   ```

   For a denied Job create, read the GKE audit log for `jobs.create` in the
   jobs namespace. Check a policy change with `kubectl apply --dry-run=server`.
   For a smoke failure, read the `worker-provisioner-launcher` logs and the
   provisioner Job pods in the jobs namespace.

7. For a Helm failure that rolled back, read the container logs from Cloud
   Logging. The atomic rollback deletes the failed pods, so `kubectl logs` has
   nothing to show.

   Read-only command:

   ```bash
   gcloud logging read 'resource.type="k8s_container" AND resource.labels.namespace_name="shifter-platform" AND resource.labels.container_name="<container>"' \
     --project <project> --freshness=1h --limit 100 --format='value(timestamp,textPayload)'
   ```

8. For a running-image failure, list the image of each container. Compare each
   image with the release manifest.

   Read-only command:

   ```bash
   kubectl -n shifter-platform get pods \
     -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[*].imageID}{"\n"}{end}'
   ```

9. For a bucket key failure, read the bucket default key, the key grants, and
   the key versions. Each bucket must use its own key, and the Storage service
   agent of the project must have `roles/cloudkms.cryptoKeyEncrypterDecrypter`
   on that key.

   Read-only command:

   ```bash
   gcloud storage buckets describe gs://<bucket> --format='value(default_kms_key)'
   gcloud kms keys get-iam-policy <key> --keyring <key-ring> --location <location> --project <project>
   gcloud kms keys versions list --key <key> --keyring <key-ring> --location <location> \
     --project <project> --format='table(name,state)'
   ```

10. For an ingress or certificate failure, compare the ingress address, the
    certificate status, and the DNS answer.

    Read-only command:

    ```bash
    kubectl -n shifter-platform get ingress platform-external \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
    kubectl -n shifter-platform get managedcertificate platform-managed-cert \
      -o jsonpath='{.spec.domains} {.status.certificateStatus}'
    dig +short <hostname>
    ```

## Resolution

Fix the cause, then run the same command again from the deployer image of the
release. Use the guide for each step that changes the deployment.

- **Inputs:** Use the deployer image of the release
  ([Get and verify the deployer image](../technical/handbook/gcp-github-less-deployment.md#get-and-verify-the-deployer-image)).
  Fix a bundle error at its source and publish the bundle again
  ([Author and publish the deployment input bundle](../technical/handbook/gcp-github-less-deployment.md#author-and-publish-the-deployment-input-bundle)).
  For an identity name that is too long, pass the identity explicitly
  ([Identity options](../technical/handbook/gcp-github-less-deployment.md#identity-options)).
- **Lock:** When the holder still runs, wait for it. When you know that the
  holder stopped, run the next command with `--break-lock`
  ([Deployment lock](../technical/handbook/gcp-github-less-deployment.md#deployment-lock)).
  The command removes the lock with no prompt.
- **Credentials:** For `Reauthentication failed`, run `gcloud auth login` or
  `gcloud auth application-default login` again. Then run the stopped command
  again. Use `--break-lock` only if the stopped run held the deployment lock.
  The commands use the active gcloud account to impersonate the purpose
  identities. A change of the active account in another shell can break the
  next gcloud call, for example the lock release after a destroy. Pin the
  account for each run with `CLOUDSDK_CORE_ACCOUNT=<operator>`.
- **Foundation:** `roles/editor` is not enough for `gcp-install` or
  `gcp-foundation`. Editor creates the service accounts and buckets, but it
  cannot set IAM policy, create custom roles, or change the audit
  configuration. The apply then stops partway with `403` errors. Get
  `roles/owner`, or `roles/resourcemanager.projectIamAdmin`,
  `roles/iam.roleAdmin`, and `roles/iam.serviceAccountAdmin`, and run the same
  command again. It continues from the resources that it created.
- **Infrastructure:** Fix the operator password secret or the operator email
  ([Create the initial secrets](../technical/handbook/gcp-github-less-deployment.md#create-the-initial-secrets)).
  A failed Terraform apply does not roll back. Fix the cause in the Terraform
  values, publish them, and deploy again
  ([Update and roll back](../technical/handbook/gcp-github-less-deployment.md#update-and-roll-back)).
  Do not remove a Terraform state lock while an apply can still run. After confirming the apply has stopped, use `terraform force-unlock`. Its lock ID is the lock-object generation number. The ID inside the lock information is different:
  `gcloud storage objects describe gs://<project>-terraform-state/shifter/<environment>/platform-core/default.tflock --format='value(generation)'`.
  A node pool that stays `RUNNING_WITH_ERROR` after a zone stockout fails the
  apply; see [GCE stockout on the provisioner node pool](#gce-stockout-on-the-provisioner-node-pool).
- **Preconditions:** The GCE range precondition gate requires
  `settings.range_cells.zone`, the `linux` role in `range-images.json`, and the
  Terraform output `range_host_service_account_email`. The `dc` role is
  optional, because a content pack supplies its own domain controller. Do not
  set the range host identity; the command reads it from the Terraform output.
  Each image in `range-images.json` must exist in the range project. A release
  that pins base images supplies them; for an older release, import the images
  with `gcp-images --store` before the first deploy. For `Range guest image check failed`, the deploy
  identity could not read an image; the message names the reason, for example
  a missing `compute.images.get` permission. For a deliberate platform-first bring-up, deploy
  with `--allow-missing-range-images`.
  If other base guest images already exist in the project, record them with
  `gcp-config set-range-image`. Record `linux` and `kali`; record `dc` only
  when the selected release includes it. The deploy imports only when a role
  named by the release is missing from the bundle.
  If an interrupted first installation imported verified images before it
  wrote `range-images.json`, retain those images. Record their exact native
  references with `gcp-config set-range-image`. Then resume
  `gcp-deploy --first-install` with the same release and store. Image readback
  and the release checks still apply.
- **Images:** Make the release packages public
  ([Make new release packages public](../dev/gcp-contributor-deploy.md#make-new-release-packages-public)),
  or deploy from a mirror with `--release-source`.
- **Scan:** Deploy a release whose images have no HIGH or CRITICAL finding with
  a fix. Read the raw report under `release-scans/`. There is no bypass.
- **Verify:** Check `settings.release_trust` against the repository that
  published the release. Do not deploy an image that fails its provenance
  check.
- **Rollout:** The Helm upgrade is atomic, so a failed upgrade rolls back the
  Helm release. Fix the cause that the events and the rollout status show, and
  deploy again. For a running-image mismatch, find the owner of the unexpected
  image before you deploy again.
- **Identity:** On an empty database the deploy writes the identity facts
  from `settings.operator_bootstrap.admin_email`; set that block. A database
  with users needs the reviewed legacy conversion facts
  ([First install](../technical/handbook/gcp-github-less-deployment.md#first-install)).
  When a cutover Job fails, read its `portal` container log in Cloud Logging
  (`resource.labels.pod_name:"identity-cutover"`). The Job is gone after the
  command stops.
- **Policy:** The deploy generates the three OpenFGA secrets
  (`shifter-<environment>-openfga-runtime`, `-admin`, `-ca`) only when none
  exists. When only some exist, restore the missing ones, or delete all three
  to regenerate them; then deploy again. A release built before #2679 has no
  authorization model: deploy a newer release, or pin
  `settings.openfga.store_id` and `model_id`. When the publisher Job fails,
  read its `publisher` container log in Cloud Logging
  (`resource.labels.pod_name:"openfga-publish"`).
- **Catalog:** The catalog Job acts as the bootstrap administrator that the
  cutover recorded, so `settings.operator_bootstrap.admin_email` must name
  that account. Otherwise sign in, issue a content credential, and deploy
  again with `--catalog-credential-file <private 0600 file>`.
- **Certificate:** Point the DNS A record of the hostname at the ingress
  address, with no proxy. The load balancer must serve the certificate
  challenge, so keep the record unproxied. Then deploy again without `--first-install`
  ([First install](../technical/handbook/gcp-github-less-deployment.md#first-install)).
  When the certificate does not appear, check that `deployment.domain` names
  the hostname. In a Cloudflare-managed zone, check for stale records from a
  prior deployment. A retained CNAME to a removed load balancer blocks the new
  A record. First issuance can take longer than one deploy run. The domain
  status can show `FailedNotVisible` for a while after the A record resolves,
  because Google checks the record again on its own schedule. In one standup it
  changed to `ACTIVE` about 45 minutes after the record resolved. No action is
  needed while the hostname resolves to the ingress address and the load
  balancer answers on port 80. A destroy releases the
  `shifter-<environment>-platform-ip` address, so a reinstall can get a
  different address ([Tear down](../technical/handbook/gcp-github-less-deployment.md#tear-down)).
- **Smoke (exit status 3):** The deployment is current. Find the cause in the
  smoke output, then run `gcp-smoke` again
  ([Smoke and exit status](../technical/handbook/gcp-github-less-deployment.md#smoke-and-exit-status)).
- **Bucket keys:** For a wrong default key, run the owner command first:
  `gcp-foundation` for the foundation buckets, `gcp-deploy` for the platform
  buckets, or your pack bucket root
  ([Upgrade a deployment to bucket keys](../technical/handbook/gcp-github-less-deployment.md#upgrade-a-deployment-to-bucket-keys)).
  For a missing grant or a disabled key version, follow
  [Repair key access](../technical/handbook/gcp-github-less-deployment.md#repair-key-access).
  For unmigrated live objects, identify the writer that selects its own key or the identity without rewrite permission. Fix that cause, then retry. A second run rewrites only the objects that remain. Do not
  remove a bucket default key to restore access.
- **Teardown:** Pass the exact deployment name to `--confirm`. Use the deployer
  image of the release that the deployment runs. After a failed destroy, run
  `gcp-destroy` again
  ([Tear down](../technical/handbook/gcp-github-less-deployment.md#tear-down)).
  GCP may report Cloud SQL, Memorystore, or GKE deleted before Service Networking
  and load-balancer dependencies observe the release. `gcp-destroy` retries the
  idempotent Terraform destroy with bounded backoff for this convergence; do not
  delete the reported dependency manually or remove it from state.

To roll back application code, deploy an earlier verified release only when its schema remains compatible.
Helm rollback does not reverse database, identity, policy, or Terraform changes.
Use [RB015](rb015-database-migrations.md) before a rollback that affects data.

## GCE stockout on the provisioner node pool

The regional cluster places one provisioner node per zone. A zone stockout for `provisioner_machine_type` can leave a pool `RUNNING_WITH_ERROR`. The apply fails after the roughly 35-minute node-pool timeout, even when other pools succeed. The stockout is
machine-type and zone specific.

Confirm an alternative type has capacity in all
of the cluster's zones (the `access` pool already proves `e2-standard-8`
availability), then set `provisioner_machine_type` to that type of the same
size class (`e2-standard-8` is the same 8 vCPU / 32 GB shape as
`n2-standard-8`). The pool runs only the provisioner launcher and the
Terraform provisioner Jobs, so a smaller E2 type, for example `e2-standard-4`,
also works. After a stockout, the pool stays `RUNNING_WITH_ERROR` and the apply
fails at the node-pool timeout.

Publish the new type in the bundle and run the
deploy again; Terraform replaces the pool. Set it in the bundle's Terraform values (`terraform.tfvars`
or `terraform.tfvars.json`). The retained CI adapter sets it in its committed
`environments/<environment>/terraform.tfvars`.

There is no node-zone tfvar. Pinning GKE node zones requires a reviewed module change, not an operator override.

## Prevention

Deploy only verified releases by digest. Keep the bundle in the config bucket,
not in a repository. Keep the evidence bucket retention lock. Do not disable or
destroy a bucket key version while data uses it.

For a foundation change, run `gcp-foundation` before `gcp-deploy`. Run the preflight
before each change. Run one lifecycle command at a time for each deployment.

Escalate a failed provenance check or a HIGH or CRITICAL finding without a fixed release. Escalate unknown lock ownership or a Terraform lock after a stopped run. Also escalate teardown outside the selected deployment or a key version that is destroyed or scheduled for destruction.
