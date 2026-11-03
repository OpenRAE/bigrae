"""Retained worker custody and caller-owned evidence holds."""

from uuid import uuid4

from django.db import models
from django.db.models.fields.json import KeyTextTransform


class WorkerPolicyRecord(models.Model):
    """One deployment-wide admission mutex and administrator-published policy."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    configuration = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="worker_policy_singleton")]

    def __str__(self) -> str:
        return "Disposable worker policy"


class RangeManagementAccess(models.Model):
    """Private generation-bound management references, outside participant state."""

    range = models.OneToOneField("Range", on_delete=models.CASCADE)
    operation_id = models.UUIDField()
    resource_generation = models.UUIDField()
    bindings = models.JSONField()

    def __str__(self) -> str:
        return f"Private management for range {self.range_id}"


class DisposableWorker(models.Model):
    """A worker never loses custody while provider resources may remain."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    range = models.OneToOneField("Range", on_delete=models.PROTECT, related_name="disposable_worker")
    request_id = models.UUIDField(unique=True)
    experiment_id = models.UUIDField(db_index=True)
    trial_id = models.UUIDField(null=True, blank=True)
    profile = models.JSONField()
    profile_digest = models.CharField(max_length=71)
    capacity_scope_ref = models.UUIDField(db_index=True)
    deadline = models.DateTimeField(db_index=True)
    retirement_at = models.DateTimeField(null=True, blank=True)
    terminal_at = models.DateTimeField(null=True, blank=True, db_index=True)
    recovery_required = models.BooleanField(default=False)
    recovery_reason = models.CharField(max_length=32, blank=True, default="")
    recovery_attempts = models.PositiveSmallIntegerField(default=0)
    max_recovery_attempts = models.PositiveSmallIntegerField()
    hold_review_seconds = models.PositiveIntegerField()
    next_recovery_at = models.DateTimeField(db_index=True)
    authorization_publication_state = models.CharField(max_length=16, default="requested")
    authorization_provider_store_id = models.CharField(max_length=128, blank=True, default="")
    authorization_model_id = models.CharField(max_length=128, blank=True, default="")
    qualification = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                KeyTextTransform("daemon_identity", "qualification"),
                condition=models.Q(qualification__has_key="daemon_identity"),
                name="worker_independent_daemon",
            ),
            models.UniqueConstraint(
                KeyTextTransform("machine_identity", "qualification"),
                condition=models.Q(qualification__has_key="machine_identity"),
                name="worker_independent_machine",
            ),
        ]

    def __str__(self) -> str:
        return f"Disposable worker {self.pk}"


class WorkerRetirementHold(models.Model):
    """One exact generation and principal own each hold until explicit release."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    worker = models.ForeignKey(DisposableWorker, on_delete=models.PROTECT, related_name="holds")
    owner_principal_uuid = models.UUIDField()
    reason = models.CharField(
        max_length=16, choices=[("evidence", "Evidence"), ("capture", "Capture"), ("operator", "Operator")]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    review_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["worker", "owner_principal_uuid"],
                condition=models.Q(released_at__isnull=True),
                name="worker_active_owner_hold",
            )
        ]

    def __str__(self) -> str:
        return f"Worker retirement hold {self.pk}"
