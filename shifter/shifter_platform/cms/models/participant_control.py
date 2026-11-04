"""Native installation and product references beside the released runtime.

These records contain no portable controller history or execution status.
Scalar source/range references retain provenance after archival; owning
services must resolve live custody before using them. No row grants authority.
"""

from uuid import uuid4

from django.db import models

from shared.db import RecordedAuthorityFields
from shared.native_participant import NATIVE_POWER_CONTROL_PROFILE_REF, NativePowerControlSelection


class ParticipantControlConfiguration(RecordedAuthorityFields):
    """One immutable organization/source mapping to the fixed native profile."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True, editable=False)
    source_uuid = models.UUIDField(db_index=True, editable=False)
    source_package_digest = models.CharField(max_length=71, editable=False)
    profile_ref = models.CharField(max_length=64, default=NATIVE_POWER_CONTROL_PROFILE_REF, editable=False)
    participant_address = models.CharField(max_length=256, editable=False)
    controller_address = models.CharField(max_length=256, editable=False)
    pause_action_contract_address = models.CharField(max_length=256, editable=False)
    resume_action_contract_address = models.CharField(max_length=256, editable=False)
    observation_boundary_address = models.CharField(max_length=256, editable=False)
    raes_version = models.CharField(max_length=64, editable=False)
    implementation_digest = models.CharField(max_length=71, editable=False)
    runtime_policy_digest = models.CharField(max_length=71, default="", editable=False)
    configuration_digest = models.CharField(max_length=71, editable=False)
    structural_report_ref = models.CharField(max_length=128, editable=False)
    retired_at = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Retain one current configuration per organization and registered source."""

        db_table = "cms_participant_control_configuration"
        constraints = [
            models.UniqueConstraint(
                fields=["organization_uuid", "source_uuid"],
                condition=models.Q(retired_at__isnull=True),
                name="cms_control_source_current",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_package_digest__regex=r"^sha256:[0-9a-f]{64}$")
                    & models.Q(implementation_digest__regex=r"^sha256:[0-9a-f]{64}$")
                    & models.Q(configuration_digest__regex=r"^sha256:[0-9a-f]{64}$")
                ),
                name="cms_control_config_digests_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(runtime_policy_digest="")
                | models.Q(runtime_policy_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="cms_control_runtime_policy_digest_valid",
            ),
        ]

    @property
    def selection(self) -> NativePowerControlSelection:
        """Project native logical references without interpreting a portable schema."""
        return NativePowerControlSelection(
            participant_address=self.participant_address,
            controller_address=self.controller_address,
            pause_action_contract_address=self.pause_action_contract_address,
            resume_action_contract_address=self.resume_action_contract_address,
            observation_boundary_address=self.observation_boundary_address,
        )

    def __str__(self) -> str:
        return f"Participant control configuration {self.pk}"


class ParticipantControlBinding(RecordedAuthorityFields):
    """Join one product subject and qualified native generation to one SDK run."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    configuration = models.ForeignKey(ParticipantControlConfiguration, on_delete=models.PROTECT)
    configuration_digest = models.CharField(max_length=71, editable=False)
    range_uuid = models.UUIDField(db_index=True, editable=False)
    compiler_binding_ref = models.UUIDField(editable=False)
    resource_generation = models.UUIDField(editable=False)
    run_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    product = models.CharField(max_length=16, editable=False)
    product_subject_uuid = models.UUIDField(editable=False)
    invalidated_at = models.DateTimeField(null=True, editable=False)
    runtime_initialized_at = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """The current range binding owns routing, not portable workflow state."""

        db_table = "cms_participant_control_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["range_uuid"],
                condition=models.Q(invalidated_at__isnull=True),
                name="cms_control_range_current",
            ),
        ]

    def __str__(self) -> str:
        return f"Participant control binding {self.pk}"


class ParticipantControlCommand(RecordedAuthorityFields):
    """One original native request and proof, without portable acceptance state."""

    id = models.UUIDField(primary_key=True, editable=False)
    dispatch_fenced_at = models.DateTimeField(null=True, editable=False)
    binding = models.ForeignKey(ParticipantControlBinding, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, editable=False)
    verb = models.CharField(max_length=8, editable=False)
    proposal_uuid = models.UUIDField(editable=False, db_index=True)
    action_uuid = models.UUIDField(editable=False, db_index=True)
    request_json = models.BinaryField(max_length=16_384, editable=False)
    subject_json = models.BinaryField(max_length=4096, editable=False)
    control_cut_digest = models.CharField(max_length=71, editable=False)
    portable_operation_uuid = models.UUIDField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Keep closed native request kinds and exact requested-cut identity."""

        db_table = "cms_participant_control_command"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["proposal", "approval", "denial", "cancellation", "action"])
                    & models.Q(verb__in=["pause", "resume"])
                    & models.Q(control_cut_digest__regex=r"^sha256:[0-9a-f]{64}$")
                ),
                name="cms_native_control_request_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Participant control command {self.pk}"
