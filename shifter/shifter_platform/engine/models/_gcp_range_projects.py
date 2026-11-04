"""Operator registrations and immutable, exclusive GCP range-project custody."""

from uuid import uuid4

from django.db import models


class GcpRangeProject(models.Model):
    """A dedicated project becomes eligible only after accepted baseline capture."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True, editable=False)
    project_id = models.CharField(max_length=30, unique=True, editable=False)
    project_number = models.CharField(max_length=20, blank=True, default="", editable=False)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    baseline = models.JSONField(null=True, editable=False)
    created_by_principal_uuid = models.UUIDField(editable=False)
    provisioner_operation_id = models.UUIDField(null=True, editable=False)
    provisioner_operation = models.CharField(max_length=32, blank=True, default="", editable=False)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Keep registration identity unique and accepted state internally consistent."""

        db_table = "engine_gcp_range_project"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "ready", "failed", "disabled"]),
                name="gcp_range_project_status",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="ready") | models.Q(baseline__isnull=False),
                name="gcp_range_project_ready_baseline",
            ),
        ]

    def __str__(self) -> str:
        """Expose an opaque registry identity, not provider metadata."""
        return f"Registered project {self.id} ({self.status})"


class GcpRangeProjectUse(models.Model):
    """One retained range lifetime; verified restoration is required to release it."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(GcpRangeProject, on_delete=models.PROTECT, related_name="uses")
    range = models.ForeignKey("engine.Range", on_delete=models.PROTECT, related_name="gcp_project_uses")
    binding = models.JSONField(editable=False)
    released_at = models.DateTimeField(null=True, editable=False)
    release_operation_id = models.UUIDField(null=True, editable=False)
    release_state_digest = models.CharField(max_length=71, blank=True, default="", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Enforce exclusivity in SQL rather than trusting an availability read."""

        db_table = "engine_gcp_range_project_use"
        constraints = [
            models.UniqueConstraint(
                fields=["project"], condition=models.Q(released_at__isnull=True), name="gcp_project_one_unreleased_use"
            ),
            models.UniqueConstraint(fields=["project", "range"], name="gcp_project_range_lifetime"),
            models.CheckConstraint(
                condition=(
                    models.Q(released_at__isnull=True, release_operation_id__isnull=True, release_state_digest="")
                    | (
                        models.Q(released_at__isnull=False, release_operation_id__isnull=False)
                        & ~models.Q(release_state_digest="")
                    )
                ),
                name="gcp_project_use_release_receipt",
            ),
        ]

    def __str__(self) -> str:
        """Keep baseline locators and project names out of implicit diagnostics."""
        return f"Registered project use {self.id}"
