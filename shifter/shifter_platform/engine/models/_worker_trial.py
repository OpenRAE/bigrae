"""One trial on one disposable worker, driven by native ``worker-trial`` operations."""

from uuid import uuid4

from django.db import models

from shared.db import RecordedAuthorityFields


class WorkerTrial(RecordedAuthorityFields):
    """Native custody of the single trial that a worker runs.

    ``owner_reference`` is the caller's opaque attempt identity; it grants no
    permission. ``staged`` and ``deadline`` are immutable after creation.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    generation = models.UUIDField(default=uuid4, editable=False)
    worker = models.OneToOneField("DisposableWorker", on_delete=models.PROTECT, related_name="trial")
    owner_reference = models.UUIDField(unique=True, editable=False)
    deadline = models.DateTimeField(editable=False)
    staged = models.JSONField(editable=False)
    state = models.CharField(max_length=16, default="pending")
    exit_code = models.PositiveSmallIntegerField(null=True, blank=True)
    sealed = models.BooleanField(default=False)
    archive = models.JSONField(null=True, blank=True)
    stop_requested = models.BooleanField(default=False)
    provisioner_operation_id = models.UUIDField(null=True, blank=True, unique=True)
    provisioner_operation = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Keep trial states closed and the exit code consistent with the state."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=("pending", "prepared", "running", "exited", "failed")),
                name="worker_trial_state_closed",
            ),
            models.CheckConstraint(
                condition=models.Q(state="exited") | models.Q(exit_code__isnull=True),
                name="worker_trial_exit_code_after_exit",
            ),
            models.CheckConstraint(
                condition=models.Q(provisioner_operation__in=("", "run", "collect")),
                name="worker_trial_operation_closed",
            ),
        ]
