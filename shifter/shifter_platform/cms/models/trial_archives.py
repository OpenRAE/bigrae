"""Tenant archive custody metadata; scientific records remain original objects."""

from uuid import uuid4

from django.db import models


class TrialArchiveDestination(models.Model):
    """An explicitly approved organization destination and retention choice."""

    organization_uuid = models.UUIDField(primary_key=True)
    bucket = models.CharField(max_length=222)
    prefix = models.CharField(max_length=256)
    retention_days = models.PositiveIntegerField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(retention_days__isnull=True) | models.Q(retention_days__gt=0),
                name="trial_destination_positive_retention",
            )
        ]

    def __str__(self) -> str:
        return f"Trial archive destination {self.organization_uuid}"


class TrialArchiveTransfer(models.Model):
    """Reserve exact storage custody before I/O, including uncertain writes."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True)
    expected = models.JSONField()
    identity_digest = models.CharField(max_length=64, db_index=True)
    bucket = models.CharField(max_length=222)
    object_key = models.CharField(max_length=512, unique=True)
    retention_days = models.PositiveIntegerField(null=True)
    archive_digest = models.CharField(max_length=64, blank=True)
    archive_bytes = models.PositiveBigIntegerField(default=0)
    object_identity = models.JSONField(default=dict)
    # settled means this invocation can no longer issue a late upload. A lost
    # cloud acknowledgement deliberately leaves it false, even on exception.
    settled = models.BooleanField(default=False)
    state = models.CharField(max_length=16, default="pending", db_index=True)
    expires_at = models.DateTimeField(null=True, db_index=True)
    failure_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "verified", "committed", "duplicate", "purging", "purged"]),
                name="trial_transfer_state",
            )
        ]

    def __str__(self) -> str:
        return f"Trial archive transfer {self.id} ({self.state})"


class TrialArchiveReceipt(models.Model):
    """The atomic custody commit; a body-free tombstone survives retention."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True)
    identity_digest = models.CharField(max_length=64)
    transfer = models.OneToOneField(TrialArchiveTransfer, on_delete=models.PROTECT)
    archive_digest = models.CharField(max_length=64)
    run_record_digest = models.CharField(max_length=71)
    run_status = models.CharField(max_length=32)
    outcome_status = models.CharField(max_length=32)
    evidence_complete = models.BooleanField()
    gap_count = models.PositiveIntegerField()
    member_count = models.PositiveIntegerField()
    state = models.CharField(max_length=16, default="committed")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization_uuid", "identity_digest"], name="unique_tenant_trial_archive_identity"
            ),
            models.CheckConstraint(condition=models.Q(state__in=["committed", "expired"]), name="trial_receipt_state"),
        ]

    def __str__(self) -> str:
        return f"Trial archive receipt {self.id} ({self.state})"
