"""Native correlation beside the incumbent launch intent, without a second ledger."""

from uuid import UUID, uuid4

from django.db import models


class ParticipantPowerReservation(models.Model):
    """Join an exact participant admission to one held native operation.

    The launch intent owns dispatch, immutable input and workload identity.
    The released runtime owns episode and control history. This row retains
    only the native correlation and the committed portable references.
    """

    launch_intent = models.OneToOneField("engine.ProvisionerLaunchIntent", on_delete=models.PROTECT)
    compiler_binding = models.ForeignKey("engine.RaesCompilerInputBinding", on_delete=models.PROTECT)
    run_id = models.UUIDField(editable=False)
    participant_address = models.CharField(max_length=256, editable=False)
    controller_address = models.CharField(max_length=256, editable=False)
    episode_id = models.CharField(max_length=256, editable=False)
    action_id = models.UUIDField(unique=True, editable=False)
    proposal_id = models.UUIDField(editable=False)
    approval_uuid = models.UUIDField(null=True, editable=False)
    meaning_digest = models.CharField(max_length=71, editable=False)
    previous_status = models.CharField(max_length=16, default="failed", editable=False)
    portable_operation_uuid = models.UUIDField(null=True, editable=False)
    control_cut_digest = models.CharField(max_length=71, blank=True, default="", editable=False)
    released_at = models.DateTimeField(null=True, editable=False)
    fenced_at = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Retain one admission correlation per native operation and action."""

        db_table = "engine_participant_power_reservation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(meaning_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="engine_participant_power_meaning_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Participant power action {self.action_id}"


class ParticipantPowerInvocation(models.Model):
    """One consumed native call permission, without a second operation status."""

    invocation_id = models.UUIDField(primary_key=True, editable=False)
    reservation = models.ForeignKey(ParticipantPowerReservation, on_delete=models.PROTECT)
    member_ref = models.CharField(max_length=512, editable=False)
    pod_uid = models.CharField(max_length=256, editable=False)
    job_uid = models.CharField(max_length=256, editable=False)
    pod_name = models.CharField(max_length=256, default="", editable=False)
    container_id = models.CharField(max_length=256, default="", editable=False)
    attempt_id = models.UUIDField(default=uuid4, editable=False)
    permission_issued = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        """Retain one immutable native permission per admitted member."""

        db_table = "engine_participant_power_invocation"
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "member_ref"],
                name="engine_power_member_invocation_once",
            ),
            models.CheckConstraint(
                condition=models.Q(permission_issued=True) | models.Q(closed_at__isnull=False),
                name="engine_power_uncalled_attempt_closed",
            ),
            models.CheckConstraint(
                condition=~models.Q(attempt_id=UUID(int=0)),
                name="engine_power_attempt_nonzero",
            ),
        ]

    def __str__(self) -> str:
        return f"Participant power invocation {self.invocation_id}"
