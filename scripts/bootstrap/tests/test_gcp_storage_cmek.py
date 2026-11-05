"""Tests for the GCS customer-managed key object migration (#2564)."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from gcp_process import ProcessResult
from gcp_storage_cmek import StorageMigrationError, migrate_bucket, migrate_buckets
from tests.gcp_test_support import FakeRunner

BUCKET = "acme-assets"
KEY = "projects/acme/locations/us-central1/keyRings/shifter-acme-gcs/cryptoKeys/assets"
OLD_KEY = "projects/acme/locations/us-central1/keyRings/other/cryptoKeys/old"


class FakeBucket:
    """Simulate one versioned bucket for the gcloud storage calls of the migration."""

    def __init__(self, objects, *, default_key=KEY, locked=False, soft_deleted=0, soft_delete_listing=True):
        self.objects = [dict(item) for item in objects]
        self.default_key = default_key
        self.locked = locked
        self.soft_deleted = soft_deleted
        self.soft_delete_listing = soft_delete_listing
        self.next_generation = 9000
        self.rewrites: list[list[str]] = []
        self.concurrent_write: str | None = None

    def runner(self, *overrides: tuple[list[str], ProcessResult]) -> FakeRunner:
        """Return a runner for this bucket; ``overrides`` answer first (first match wins)."""
        runner = FakeRunner()
        for prefix, result in overrides:
            runner.on(prefix, result)
        return (
            runner.on(["gcloud", "storage", "buckets", "describe", f"gs://{BUCKET}"], self.describe)
            .on(["gcloud", "storage", "objects", "list", f"gs://{BUCKET}/**", "--soft-deleted"], self.list_soft_deleted)
            .on(["gcloud", "storage", "objects", "list", f"gs://{BUCKET}/**"], self.list)
            .on(["gcloud", "storage", "objects", "update"], self.update)
        )

    def describe(self, argv: Sequence[str], env, stdin) -> ProcessResult:
        metadata: dict[str, object] = {"name": BUCKET}
        if self.default_key:
            metadata["encryption"] = {"defaultKmsKeyName": self.default_key}
        if self.locked:
            metadata["retentionPolicy"] = {"retentionPeriod": "7776000", "isLocked": True}
        return ProcessResult(0, json.dumps(metadata))

    def list(self, argv: Sequence[str], env, stdin) -> ProcessResult:
        return ProcessResult(0, json.dumps(self.objects))

    def list_soft_deleted(self, argv: Sequence[str], env, stdin) -> ProcessResult:
        if not self.soft_delete_listing:
            return ProcessResult(1, "", "AccessDeniedException: 403")
        return ProcessResult(
            0, json.dumps([{"name": f"gone-{i}", "generation": str(i)} for i in range(self.soft_deleted)])
        )

    def _write(self, name: str, kms: str | None) -> None:
        for item in self.objects:
            if item["name"] == name and "timeDeleted" not in item:
                item["timeDeleted"] = "2026-11-02T00:00:00Z"
        new = {"name": name, "generation": str(self.next_generation)}
        if kms:
            new["kmsKeyName"] = kms
        self.next_generation += 1
        self.objects.append(new)

    def update(self, argv: Sequence[str], env, stdin) -> ProcessResult:
        assert argv[4] == "--read-paths-from-stdin" and stdin.endswith("\n") and stdin.count("\n") == 1
        url = stdin.strip()
        self.rewrites.append([*argv, url])
        name, _, generation = url.removeprefix(f"gs://{BUCKET}/").rpartition("#")
        key = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--encryption-key="))
        match = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--if-generation-match="))
        if self.concurrent_write == name:
            # A writer replaces the object after the listing; it uses the bucket default key.
            self._write(name, f"{self.default_key}/cryptoKeyVersions/1")
            self.concurrent_write = None
        live = next(item for item in self.objects if item["name"] == name and "timeDeleted" not in item)
        if live["generation"] != match or generation != match:
            return ProcessResult(1, "", "PreconditionException: 412 At least one of the pre-conditions did not hold.")
        self._write(name, f"{key}/cryptoKeyVersions/3")
        return ProcessResult(0)

    def live_keys(self) -> dict[str, str | None]:
        return {item["name"]: item.get("kmsKeyName") for item in self.objects if "timeDeleted" not in item}


def _live(name: str, generation: str, kms: str | None = None) -> dict[str, str]:
    item = {"name": name, "generation": generation}
    if kms:
        item["kmsKeyName"] = kms
    return item


def _noncurrent(name: str, generation: str) -> dict[str, str]:
    return {"name": name, "generation": generation, "timeDeleted": "2026-01-01T00:00:00Z"}


class TestMigrateBucket:
    def test_rewrites_only_live_objects_that_do_not_use_the_bucket_key(self):
        bucket = FakeBucket(
            [
                _live("agents/a.msi", "11"),
                _live("agents/b.msi", "12", f"{OLD_KEY}/cryptoKeyVersions/1"),
                _live("agents/c.msi", "13", f"{KEY}/cryptoKeyVersions/2"),
                _noncurrent("agents/a.msi", "5"),
            ],
            soft_deleted=2,
        )
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        rewritten = sorted(argv[-1] for argv in bucket.rewrites)
        assert rewritten == [f"gs://{BUCKET}/agents/a.msi#11", f"gs://{BUCKET}/agents/b.msi#12"]
        # Each rewrite pins the listed generation, so it can not replace a newer object.
        for argv in bucket.rewrites:
            generation = argv[-1].rpartition("#")[2]
            assert argv[5:-1] == [f"--encryption-key={KEY}", f"--if-generation-match={generation}"]
        assert all(kms and kms.startswith(KEY + "/") for kms in bucket.live_keys().values())
        assert report.rewritten == 2 and report.customer_managed == 3
        # The original generations stay as noncurrent residuals; they are never rewritten or deleted.
        assert report.noncurrent_residual == 3 and report.soft_deleted_residual == 2
        assert report.retained_residual == 0 and report.unaddressable_residual == 0

    def test_a_second_run_rewrites_nothing(self):
        bucket = FakeBucket([_live("a", "1", f"{KEY}/cryptoKeyVersions/1"), _noncurrent("a", "0")])
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        assert bucket.rewrites == [] and report.rewritten == 0 and report.noncurrent_residual == 1

    def test_a_concurrent_write_is_never_replaced_by_older_bytes(self):
        bucket = FakeBucket([_live("report.json", "21")])
        bucket.concurrent_write = "report.json"
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        # The precondition fails, the newer object already uses the bucket key, and the run converges.
        (live,) = [item for item in bucket.objects if "timeDeleted" not in item]
        assert live["generation"] == "9000" and live["kmsKeyName"].startswith(KEY + "/")
        assert report.rewritten == 0 and report.customer_managed == 1

    def test_a_retention_locked_bucket_is_inventoried_and_never_rewritten(self):
        bucket = FakeBucket([_live("packer-builds/x.json", "31"), _live("deployments/y.json", "32")], locked=True)
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        assert bucket.rewrites == []
        assert report.retained_residual == 2 and report.rewritten == 0

    def test_wildcard_names_are_reported_and_not_addressed(self):
        bucket = FakeBucket([_live("uploads/report[1].pdf", "41"), _live("uploads/*.txt", "42"), _live("ok", "43")])
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        assert [argv[-1] for argv in bucket.rewrites] == [f"gs://{BUCKET}/ok#43"]
        assert report.unaddressable_residual == 2 and report.rewritten == 1

    def test_a_name_with_a_hash_keeps_its_full_name(self):
        bucket = FakeBucket([_live("notes#draft", "51")])
        migrate_bucket(bucket.runner(), BUCKET, KEY)
        assert [argv[-1] for argv in bucket.rewrites] == [f"gs://{BUCKET}/notes#draft#51"]
        assert bucket.live_keys()["notes#draft"].startswith(KEY + "/")

    def test_a_bucket_without_the_expected_default_key_stops_before_any_rewrite(self):
        for default_key in ("", OLD_KEY):
            bucket = FakeBucket([_live("a", "1")], default_key=default_key)
            with pytest.raises(StorageMigrationError, match="default key"):
                migrate_bucket(bucket.runner(), BUCKET, KEY)
            assert bucket.rewrites == []

    def test_an_object_that_stays_google_managed_fails_without_naming_it(self, capsys):
        bucket = FakeBucket([_live("private/secret-name.bin", "61")])
        runner = bucket.runner((["gcloud", "storage", "objects", "update"], ProcessResult(1, "", "403 denied")))
        with pytest.raises(StorageMigrationError) as caught:
            migrate_bucket(runner, BUCKET, KEY)
        assert "1 live object" in str(caught.value)
        assert "secret-name" not in str(caught.value) and "secret-name" not in capsys.readouterr().out

    def test_the_report_prints_counts_and_no_object_names(self, capsys):
        bucket = FakeBucket([_live("private/customer-file.bin", "71")])
        runner = bucket.runner()
        migrate_bucket(runner, BUCKET, KEY)
        out = capsys.readouterr().out
        assert "customer-file" not in out and BUCKET in out and "rewrote 1" in out
        # The object URL travels on stdin, so the logged argv names no object (#2564).
        (update,) = runner.find("gcloud", "storage", "objects", "update")
        assert not any("customer-file" in arg for arg in update.argv)
        assert update.input_text == f"gs://{BUCKET}/private/customer-file.bin#71\n"

    def test_unreadable_listing_fails(self):
        runner = FakeBucket([]).runner((["gcloud", "storage", "objects", "list"], ProcessResult(0, "not json")))
        with pytest.raises(StorageMigrationError, match="listing"):
            migrate_bucket(runner, BUCKET, KEY)

    def test_an_unavailable_soft_delete_listing_is_reported_as_unknown(self, capsys):
        bucket = FakeBucket([_live("a", "1", f"{KEY}/cryptoKeyVersions/1")], soft_delete_listing=False)
        report = migrate_bucket(bucket.runner(), BUCKET, KEY)
        assert report.soft_deleted_residual is None
        assert "soft-deleted count unknown" in capsys.readouterr().out

    def test_the_identity_environment_reaches_every_call(self):
        bucket = FakeBucket([_live("a", "1")])
        runner = bucket.runner()
        migrate_bucket(runner, BUCKET, KEY, env={"CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT": "deploy@x"})
        assert runner.calls and all(
            call.env.get("CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT") == "deploy@x" for call in runner.calls
        )


class TestMigrateBuckets:
    def test_migrates_each_bucket_with_its_own_key(self):
        bucket = FakeBucket([_live("a", "1")])
        reports = migrate_buckets(bucket.runner(), {BUCKET: KEY})
        assert [report.bucket for report in reports] == [BUCKET]

    def test_rejects_a_malformed_bucket_map(self):
        with pytest.raises(StorageMigrationError, match="bucket"):
            migrate_buckets(FakeRunner(), {BUCKET: ""})
        with pytest.raises(StorageMigrationError, match="bucket"):
            migrate_buckets(FakeRunner(), [BUCKET])  # type: ignore[arg-type]
