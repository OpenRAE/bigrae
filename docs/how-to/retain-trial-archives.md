# Retain trial archives

Central archive custody keeps original trial evidence after a worker is removed.
A collection receipt confirms verified storage of the declared archive bytes.
It does not confirm scientific success or cloud resource cleanup.

## Configure an approved destination

Use an existing approved bucket on the installation's configured cloud provider.
Do not create a bucket for this command without approval.
Configure its IAM, encryption, backup, and lifecycle policy for the evidence sensitivity.
Workers must not have overwrite or delete access to central evidence.
The bucket lifecycle must preserve the promised retention window.
Account for noncurrent versions when bucket versioning is enabled.

Use a native credential with installation and organization content-management authority for configuration.
The credential file must be owner-controlled, regular, and mode `0600`.
It contains an issued bearer proof, not a user name or credential identifier.
Do not pass the proof in command arguments.

Run the database migrations before the first configuration.
Then configure one organization:

```shell
python manage.py trial_archive configure \
  --credential-file /private/operator-proof \
  --organization "$ORGANIZATION_UUID" \
  --bucket "$APPROVED_BUCKET" --prefix trial-evidence \
  --retention-days 90
```

Use `--keep-indefinitely` instead of `--retention-days` for indefinite retention.
Finite retention must be between 1 and 36500 days.
There is no default destination or retention choice.
Configuration changes apply to new transfers.
Existing transfers and receipts retain their original destination and policy.
No storage deployment or external upload occurs during configuration.

## Collect a sealed run export

Export the existing sealed archive with its full inventory.
Include the admitted plan and all declared evidence records and chunks.
Keep original hydrated SDL, provenance, prompts, authorized content, and traces in that inventory.
Retain security exports, native realization evidence, usage, capture-loss, and cleanup records too.
Exclude credentials under the producer's redaction policy before sealing.
Keep each JSON document within 4 MiB.
Use declared chunks, JSON Lines, or binary streams for larger traces.
Intake rejects recognizable credentials; it does not rewrite original evidence.

Supply the expected identities independently of the archive.
The experiment identifier is the admitted plan's study reference identifier.
For a plan without a study, use its authoring-input reference identifier.
The run identifier names the retained RAES run.
The attempt identifier must occur in that run's execution accounting or trial provenance.
Supply the admitted plan digest, entry digest, and expected run version too.

```shell
python manage.py trial_archive intake \
  --credential-file /private/tenant-proof \
  --organization "$ORGANIZATION_UUID" \
  --archive /private/exports/trial.tar.gz \
  --experiment "$EXPERIMENT_ID" --plan "$PLAN_ID" \
  --entry "$ENTRY_ID" --run "$RUN_ID" --attempt "$ATTEMPT_ID" \
  --plan-digest "$PLAN_DIGEST" --entry-digest "$ENTRY_DIGEST" \
  --run-version "$RUN_VERSION"
```

Intake requires organization content-management authority.
The command writes a JSON collection result.
Remove the worker's evidence copy only when `worker_copy_disposable` is `true`.
Keep the receipt identifier with the experiment's operational records.
Failed and partial trials can receive collection receipts.
Read their original outcome and capture-loss records before interpreting results.

## Recover an incomplete collection

Keep the worker copy when intake fails or its response is lost.
List the organization's collections with content-read authority:

```shell
python manage.py trial_archive list \
  --credential-file /private/tenant-proof --organization "$ORGANIZATION_UUID" \
  --limit 100 --offset 0
```

Increase `--offset` to read the next page.
Pending transfers and validation failures remain visible without a disposal authorization.
`invalid-archive` indicates an inventory, structure, record, or credential rejection.
Validate the original export at its producer to locate the specific defect.
`transfer-unverified` indicates an unverified transfer or publication failure.
Retry with the same original archive and expected identities.
An identical committed delivery returns the same receipt.
Different bytes under a committed identity conflict, including after retention expiry.
Do not recompress the archive between retries.

A retry without a committed receipt uses a fresh object key.
An unknown upload outcome can still produce a late object.
Its journal remains available for operator recovery.
Do not manually delete unknown transfer objects until their writer can no longer write.
The service does not automatically discard these recovery candidates.

## Retrieve and expire evidence

Retrieval requires organization content-read authority and an unexpired receipt.
The output path must not exist.

```shell
python manage.py trial_archive retrieve \
  --credential-file /private/tenant-proof --organization "$ORGANIZATION_UUID" \
  --receipt "$RECEIPT_UUID" --output /private/restored-trial.tar.gz
```

The service verifies the stored object version, byte count, and digest before publishing the local file.
It does not create public links or signed download URLs.
Finite retention blocks retrieval at expiry, even when storage deletion fails.
Run authorized retention cleanup periodically:

```shell
python manage.py trial_archive purge \
  --credential-file /private/tenant-proof --organization "$ORGANIZATION_UUID" --limit 100
```

Purge requires organization content-management authority.
It deletes expired committed objects and expired settled duplicate or abandoned objects.
Failed deletion remains retryable.
Receipt tombstones remain for identity conflict checks.
Provider lifecycle rules govern any noncurrent cloud versions.
Pack removal, range deletion, and worker teardown do not remove these archives.

See the [service contract](../technical/shifter_platform/trial-archive-custody.md) for receipt semantics and bounds.
