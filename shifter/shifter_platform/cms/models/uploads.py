"""Native upload admission, immutable storage identity and quota reservation."""

from __future__ import annotations

from uuid import uuid4

from django.db import models

from shared.db import RecordedAuthorityFields


class AgentUploadBudget(models.Model):
    """Serialize admission for one actual customer scope, including empty scopes."""

    scope_digest = models.CharField(max_length=71, primary_key=True, editable=False)

    def __str__(self) -> str:
        return self.scope_digest


class AgentUpload(RecordedAuthorityFields):
    """Reference-only record behind the incumbent signed upload token."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    scope_digest = models.CharField(max_length=71, editable=False, db_index=True)
    name = models.CharField(max_length=100, editable=False)
    filename = models.CharField(max_length=255, editable=False)
    os_slug = models.CharField(max_length=100, editable=False)
    agent_type = models.CharField(max_length=30, editable=False)
    asset_kind = models.CharField(max_length=16, default="agent", editable=False)
    replaces_file = models.ForeignKey(
        "cms.NamedFileAsset", null=True, on_delete=models.PROTECT, editable=False, related_name="replacement_uploads"
    )
    replacement_generation = models.PositiveBigIntegerField(default=0, editable=False)
    file_owner_uuid = models.UUIDField(null=True, editable=False)
    file_size = models.PositiveBigIntegerField(editable=False)
    storage_provider = models.CharField(max_length=16, editable=False)
    storage_bucket = models.CharField(max_length=255, editable=False)
    staging_key = models.CharField(max_length=500, unique=True, editable=False)
    install_key = models.CharField(max_length=500, unique=True, editable=False)
    expires_at = models.DateTimeField(editable=False)
    state = models.CharField(max_length=16, default="issued", editable=False, db_index=True)
    cleanup_pending = models.BooleanField(default=True, editable=False)
    validated_identity = models.JSONField(default=dict, editable=False)
    validated_sha256 = models.CharField(max_length=64, default="", editable=False)
    agent = models.ForeignKey("cms.AgentConfig", null=True, on_delete=models.PROTECT, editable=False)
    file_asset = models.ForeignKey("cms.NamedFileAsset", null=True, on_delete=models.PROTECT, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Declare persistence tables, indexes and custody constraints."""

        constraints = [
            models.CheckConstraint(condition=models.Q(file_size__gt=0), name="agent_upload_positive_size"),
            models.CheckConstraint(condition=models.Q(asset_kind__in=("agent", "file")), name="upload_asset_kind"),
            models.CheckConstraint(
                condition=(
                    models.Q(asset_kind="agent", file_asset__isnull=True, replaces_file__isnull=True)
                    | models.Q(
                        asset_kind="file", agent__isnull=True, agent_type="", os_slug="", file_owner_uuid__isnull=False
                    )
                ),
                name="upload_asset_reference_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("issued", "finalizing", "completed", "cancelled")),
                name="agent_upload_valid_state",
            ),
        ]
