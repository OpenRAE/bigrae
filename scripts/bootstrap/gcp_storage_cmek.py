"""Live object migration to a bucket's customer-managed key (#2564).

A bucket default key applies only to new writes. After the owner root sets the
key, this module rewrites each live object that does not use it, in place:

- every rewrite pins the listed generation (``--if-generation-match``), so it can
  not replace an object that a concurrent writer stored after the listing;
- a bucket with a locked retention policy holds immutable evidence, so it is
  listed and never rewritten;
- native project state keeps its validated lease-specific customer-supplied key;
- noncurrent and soft-deleted generations stay as they are: a rewrite of a
  noncurrent generation would make a new live object.

The report prints counts only. Object names are private operational data and
never reach argv, a log, or an error message.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from bootstrap_core import info, warn
from gcp_process import ProcessRunner

# gcloud storage reads these characters in a URL as wildcards (wildcard_iterator).
_WILDCARD_RE = re.compile(r"[*?\[\]]")
_PROJECT_STATE_RE = re.compile(r"raes/project-state/[0-9a-f]{32}/default\.tfstate", re.ASCII)
# Raw API field names (kmsKeyName, timeDeleted, retentionPolicy) as JSON.
_RAW_JSON = ("--raw", "--format=json")


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
    customer_supplied_state: int = 0


def _uses_key(item: Mapping[str, object], key: str) -> bool:
    """Return whether an object generation is encrypted with ``key`` (any key version)."""
    kms = str(item.get("kmsKeyName") or "")
    return kms == key or kms.startswith(f"{key}/cryptoKeyVersions/")


def _uses_project_state_key(item: Mapping[str, object]) -> bool:
    """Validate the native state path and provider-owned encryption metadata."""
    if not _PROJECT_STATE_RE.fullmatch(str(item.get("name", ""))) or item.get("kmsKeyName"):
        return False
    encryption = item.get("customerEncryption")
    if not isinstance(encryption, Mapping) or encryption.get("encryptionAlgorithm") != "AES256":
        return False
    digest = encryption.get("keySha256")
    if not isinstance(digest, str):
        return False
    try:
        decoded = base64.b64decode(digest, validate=True)
    except ValueError:
        return False
    return len(decoded) == 32 and base64.b64encode(decoded).decode("ascii") == digest


def _json(runner: ProcessRunner, argv: list[str], env: Mapping[str, str | None] | None, what: str) -> object:
    """Run a gcloud command with raw JSON output and parse it."""
    result = runner.run([*argv, *_RAW_JSON], env=env)
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        raise StorageMigrationError(f"The {what} is not readable JSON") from None


def _bucket_metadata(
    runner: ProcessRunner, bucket: str, key: str, env: Mapping[str, str | None] | None
) -> dict[str, object]:
    """Return the bucket metadata after a check that its default key is ``key``."""
    metadata = _json(runner, ["gcloud", "storage", "buckets", "describe", f"gs://{bucket}"], env, "bucket")
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
        runner, ["gcloud", "storage", "objects", "list", f"gs://{bucket}/**"], env, f"bucket {bucket} listing"
    )
    items = [] if items is None else items
    if not isinstance(items, list) or not all(isinstance(item, dict) and item.get("name") for item in items):
        raise StorageMigrationError(f"The bucket {bucket} listing is not a list of objects")
    return items


def _soft_deleted_count(runner: ProcessRunner, bucket: str, env: Mapping[str, str | None] | None) -> int | None:
    """Return the number of soft-deleted objects, or None when the listing is not available."""
    argv = ["gcloud", "storage", "objects", "list", f"gs://{bucket}/**", "--soft-deleted", "--exhaustive"]
    result = runner.run([*argv, *_RAW_JSON], env=env, check=False)
    items: object = None
    if result.returncode == 0:
        try:
            items = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            items = None
    return len(items) if isinstance(items, list) else None


def _is_live(item: Mapping[str, object]) -> bool:
    """Return whether an object generation is the live version (not noncurrent)."""
    return not item.get("timeDeleted")


def _needs_rewrite(item: Mapping[str, object], key: str) -> bool:
    """Return whether a generation is a live, addressable object that does not use ``key``."""
    addressable = bool(item.get("generation")) and not _WILDCARD_RE.search(str(item["name"]))
    return _is_live(item) and addressable and not _uses_key(item, key) and not _uses_project_state_key(item)


def _rewrite_live_objects(runner: ProcessRunner, bucket: str, key: str, env: Mapping[str, str | None] | None) -> int:
    """Rewrite each live object that does not use ``key``; return the number of rewrites."""
    rewritten = 0
    for item in filter(lambda candidate: _needs_rewrite(candidate, key), _generations(runner, bucket, env)):
        generation = str(item["generation"])
        # The object URL travels on stdin, so no object name reaches argv or the
        # command log. gcloud parses "#<digits>" at the end as the source generation.
        result = runner.run(
            ["gcloud", "storage", "objects", "update", "--read-paths-from-stdin"]
            + [f"--encryption-key={key}", f"--if-generation-match={generation}"],
            env=env,
            input_text=f"gs://{bucket}/{item['name']}#{generation}\n",
            check=False,
        )
        # A failed precondition means a newer object replaced this one; the
        # verification decides whether the newer object uses the key.
        rewritten += result.returncode == 0
    return rewritten


def _verified_report(
    after: list[dict[str, object]],
    bucket: str,
    key: str,
    *,
    locked: bool,
    rewritten: int,
    soft_deleted: int | None,
) -> MigrationReport:
    """Count the generations after the rewrite; fail when an addressable live object still lacks ``key``."""
    live = [item for item in after if _is_live(item)]
    pending = [item for item in live if not _uses_key(item, key) and not _uses_project_state_key(item)]
    supplied_state = sum(1 for item in live if _uses_project_state_key(item))
    retained = pending if locked else []
    unaddressable = [] if locked else [item for item in pending if _WILDCARD_RE.search(str(item["name"]))]
    unmigrated = len(pending) - len(retained) - len(unaddressable)
    if unmigrated:
        noun = "object" if unmigrated == 1 else "objects"
        raise StorageMigrationError(f"Bucket {bucket}: {unmigrated} live {noun} do not use {key} after the rewrite")
    return MigrationReport(
        bucket=bucket,
        rewritten=rewritten,
        customer_managed=len(live) - len(pending) - supplied_state,
        noncurrent_residual=sum(1 for item in after if not _is_live(item) and not _uses_key(item, key)),
        soft_deleted_residual=soft_deleted,
        retained_residual=len(retained),
        unaddressable_residual=len(unaddressable),
        customer_supplied_state=supplied_state,
    )


def migrate_bucket(
    runner: ProcessRunner, bucket: str, key: str, *, env: Mapping[str, str | None] | None = None
) -> MigrationReport:
    """Rewrite the live objects of ``bucket`` that do not use ``key``, then verify and report."""
    retention = _bucket_metadata(runner, bucket, key, env).get("retentionPolicy")
    locked = isinstance(retention, dict) and bool(retention.get("isLocked"))
    rewritten = 0 if locked else _rewrite_live_objects(runner, bucket, key, env)
    after = _generations(runner, bucket, env)
    soft_deleted = _soft_deleted_count(runner, bucket, env)
    report = _verified_report(after, bucket, key, locked=locked, rewritten=rewritten, soft_deleted=soft_deleted)
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
    if report.customer_supplied_state:
        info(f"{report.bucket}: {report.customer_supplied_state} native state objects retain customer-supplied keys")
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
