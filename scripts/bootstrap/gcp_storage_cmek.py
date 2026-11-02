"""Live object migration to a bucket's customer-managed key (#2564).

A bucket default key applies only to new writes. After the owner root sets the
key, this module rewrites each live object that does not use it, in place:

- every rewrite pins the listed generation (``--if-generation-match``), so it can
  not replace an object that a concurrent writer stored after the listing;
- a bucket with a locked retention policy holds immutable evidence, so it is
  listed and never rewritten;
- noncurrent and soft-deleted generations stay as they are: a rewrite of a
  noncurrent generation would make a new live object.

The report prints counts only. Object names are private operational data and
never reach a log or an error message.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from bootstrap_core import info, warn
from gcp_process import ProcessRunner

# gcloud storage reads these characters in a URL as wildcards (wildcard_iterator).
_WILDCARD_RE = re.compile(r"[*?\[\]]")


class StorageMigrationError(RuntimeError):
    """The object migration can not complete; the message names no object."""


@dataclass(frozen=True)
class MigrationReport:
    """The object counts of one bucket after its migration."""

    bucket: str
    rewritten: int
    customer_managed: int
    noncurrent_residual: int
    soft_deleted_residual: int | None
    retained_residual: int
    unaddressable_residual: int


def _uses_key(item: Mapping[str, object], key: str) -> bool:
    """Return whether an object generation is encrypted with ``key`` (any key version)."""
    kms = str(item.get("kmsKeyName") or "")
    return kms == key or kms.startswith(f"{key}/cryptoKeyVersions/")


def _json(runner: ProcessRunner, argv: list[str], env: Mapping[str, str | None] | None, what: str) -> object:
    """Run a gcloud command with raw JSON output and parse it."""
    result = runner.run(argv, env=env)
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        raise StorageMigrationError(f"The {what} is not readable JSON") from None


def _bucket_metadata(
    runner: ProcessRunner, bucket: str, key: str, env: Mapping[str, str | None] | None
) -> dict[str, object]:
    """Return the bucket metadata after a check that its default key is ``key``."""
    metadata = _json(
        runner, ["gcloud", "storage", "buckets", "describe", f"gs://{bucket}", "--raw", "--format=json"], env, "bucket"
    )
    if not isinstance(metadata, dict):
        raise StorageMigrationError(f"Bucket {bucket} metadata is not readable")
    encryption = metadata.get("encryption")
    default_key = encryption.get("defaultKmsKeyName") if isinstance(encryption, dict) else None
    if default_key != key:
        raise StorageMigrationError(f"Bucket {bucket} default key is not {key}; apply its owner root first")
    return metadata


def _generations(runner: ProcessRunner, bucket: str, env: Mapping[str, str | None] | None) -> list[dict[str, object]]:
    """Return every live and noncurrent object generation of the bucket."""
    items = _json(
        runner,
        ["gcloud", "storage", "objects", "list", f"gs://{bucket}/**", "--raw", "--format=json"],
        env,
        f"bucket {bucket} listing",
    )
    items = [] if items is None else items
    if not isinstance(items, list) or not all(isinstance(item, dict) and item.get("name") for item in items):
        raise StorageMigrationError(f"The bucket {bucket} listing is not a list of objects")
    return items


def _soft_deleted_count(runner: ProcessRunner, bucket: str, env: Mapping[str, str | None] | None) -> int | None:
    """Return the number of soft-deleted objects, or None when the listing is not available."""
    argv = ["gcloud", "storage", "objects", "list", f"gs://{bucket}/**", "--soft-deleted", "--exhaustive"]
    result = runner.run([*argv, "--raw", "--format=json"], env=env, check=False)
    if result.returncode != 0:
        return None
    try:
        items = json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        return None
    return len(items) if isinstance(items, list) else 0 if items is None else None


def _is_live(item: Mapping[str, object]) -> bool:
    return not item.get("timeDeleted")


def migrate_bucket(
    runner: ProcessRunner, bucket: str, key: str, *, env: Mapping[str, str | None] | None = None
) -> MigrationReport:
    """Rewrite the live objects of ``bucket`` that do not use ``key``, then verify and report."""
    metadata = _bucket_metadata(runner, bucket, key, env)
    retention = metadata.get("retentionPolicy")
    locked = isinstance(retention, dict) and bool(retention.get("isLocked"))
    rewritten = 0
    if not locked:
        for item in _generations(runner, bucket, env):
            name, generation = str(item["name"]), str(item.get("generation", ""))
            if not _is_live(item) or _uses_key(item, key) or _WILDCARD_RE.search(name) or not generation:
                continue
            # The URL carries the source generation; gcloud parses "#<digits>" at the end only.
            flags = [f"--encryption-key={key}", f"--if-generation-match={generation}"]
            update = ["gcloud", "storage", "objects", "update"]
            result = runner.run(
                [*update, f"gs://{bucket}/{name}#{generation}", *flags],
                env=env,
                check=False,
                display_argv=[*update, f"gs://{bucket}/<object>", *flags],
            )
            # A failed precondition means a newer object replaced this one; the
            # verification below decides whether the newer object uses the key.
            rewritten += result.returncode == 0
    after = _generations(runner, bucket, env)
    live = [item for item in after if _is_live(item)]
    pending = [item for item in live if not _uses_key(item, key)]
    unaddressable = [item for item in pending if _WILDCARD_RE.search(str(item["name"]))]
    retained = pending if locked else []
    unmigrated = len(pending) - len(retained) - (0 if locked else len(unaddressable))
    if unmigrated:
        noun = "object" if unmigrated == 1 else "objects"
        raise StorageMigrationError(f"Bucket {bucket}: {unmigrated} live {noun} do not use {key} after the rewrite")
    report = MigrationReport(
        bucket=bucket,
        rewritten=rewritten,
        customer_managed=len(live) - len(pending),
        noncurrent_residual=sum(1 for item in after if not _is_live(item) and not _uses_key(item, key)),
        soft_deleted_residual=_soft_deleted_count(runner, bucket, env),
        retained_residual=len(retained),
        unaddressable_residual=0 if locked else len(unaddressable),
    )
    _print_report(report)
    return report


def _print_report(report: MigrationReport) -> None:
    """Print the counts of one bucket; no object name appears."""
    soft = (
        "soft-deleted count unknown"
        if report.soft_deleted_residual is None
        else (f"{report.soft_deleted_residual} soft-deleted")
    )
    info(
        f"{report.bucket}: rewrote {report.rewritten} live objects; "
        f"{report.customer_managed} live objects use the bucket key"
    )
    residuals = (
        f"{report.noncurrent_residual} noncurrent, {soft}, {report.retained_residual} under a locked retention "
        f"policy, {report.unaddressable_residual} with wildcard characters in the name"
    )
    if report.noncurrent_residual or report.retained_residual or report.unaddressable_residual:
        warn(f"{report.bucket}: objects that do not use the bucket key: {residuals}")
    else:
        info(f"{report.bucket}: residuals: {residuals}")


def migrate_buckets(
    runner: ProcessRunner, buckets: Mapping[str, str], *, env: Mapping[str, str | None] | None = None
) -> list[MigrationReport]:
    """Migrate each bucket of a Terraform ``storage_cmek_buckets`` map to its key."""
    if not isinstance(buckets, Mapping) or not all(
        isinstance(bucket, str) and bucket and isinstance(key, str) and key for bucket, key in buckets.items()
    ):
        raise StorageMigrationError("storage_cmek_buckets must map each bucket name to its key")
    return [migrate_bucket(runner, bucket, key, env=env) for bucket, key in sorted(buckets.items())]
