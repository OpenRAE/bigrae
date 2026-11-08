"""Immutable scientific custody and a separate mutable entry dispatch journal."""

from uuid import uuid4

from django.db import models


class ExperimentBatch(models.Model):
    """A complete admitted plan and its exact bounded original inputs."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True, editable=False)
    plan_id = models.CharField(max_length=128, editable=False)
    retained_json = models.TextField(editable=False)
    retained_digest = models.CharField(max_length=64, editable=False)
    concurrency = models.PositiveIntegerField(editable=False)
    #: A dispatch stop blocks new claims and trial starts; collection and cleanup continue.
    dispatch_stopped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Keep one immutable tenant plan and a positive dispatch bound."""

        constraints = [
            models.UniqueConstraint(fields=["organization_uuid", "plan_id"], name="experiment_tenant_plan_unique"),
            models.CheckConstraint(condition=models.Q(concurrency__gt=0), name="experiment_concurrency_positive"),
        ]

    def __str__(self) -> str:
        """Return only an opaque administrative reference."""
        return f"Experiment batch {self.id}"


class ExperimentEntry(models.Model):
    """An immutable plan/run index plus one conservatively fenced attempt."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    batch = models.ForeignKey(ExperimentBatch, on_delete=models.PROTECT)
    organization_uuid = models.UUIDField(db_index=True, editable=False)
    plan_entry_id = models.CharField(max_length=128, editable=False)
    run_id = models.CharField(max_length=128, editable=False)
    token = models.UUIDField(null=True, unique=True, editable=False)
    state = models.CharField(max_length=16, default="pending")
    worker_ref = models.CharField(max_length=256, blank=True)
    receipt = models.ForeignKey("cms.TrialArchiveReceipt", on_delete=models.PROTECT, null=True)
    cleanup_receipt_json = models.TextField(blank=True, default="")
    #: Set once before trial inputs are staged, so every stager stages the same bytes.
    trial_deadline = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Protect allocation identity and closed attempt state in the database."""

        constraints = [
            models.UniqueConstraint(
                fields=["organization_uuid", "plan_entry_id"], name="experiment_tenant_entry_unique"
            ),
            models.UniqueConstraint(fields=["organization_uuid", "run_id"], name="experiment_tenant_run_unique"),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "claimed", "running", "finished", "failed"]),
                name="experiment_entry_state",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", token__isnull=True)
                    | (~models.Q(state="pending") & models.Q(token__isnull=False))
                ),
                name="experiment_entry_claim_state",
            ),
        ]

    def __str__(self) -> str:
        """Return only an opaque administrative reference."""
        return f"Experiment entry {self.id}"
