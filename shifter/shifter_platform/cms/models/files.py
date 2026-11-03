"""Scoped immutable file versions and their admitted range uses."""

from uuid import UUID, uuid4

from django.conf import settings
from django.db import models
from django.db.models.functions import Coalesce

from cms.models.assets import FileAsset
from shared.db import RecordedAuthorityFields


class NamedFileAsset(FileAsset):
    """An opaque uploaded version; replacement creates a new row and object."""

    asset_uuid = models.UUIDField(default=uuid4, editable=False, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cms_files"
    )
    storage_provider = models.CharField(max_length=16, editable=False)
    storage_bucket = models.CharField(max_length=255, editable=False)
    object_identity = models.JSONField(editable=False)
    storage_deleted_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        """Keep native custody, byte bounds and active owner/scope names unique."""

        ordering = ["name", "-created_at"]
        base_manager_name = "all_objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    owner_principal_uuid__isnull=False, scope_kind="account", account_uuid__isnull=False
                ),
                name="named_file_native_custody",
            ),
            models.CheckConstraint(
                condition=models.Q(file_size_bytes__gt=0, file_size_bytes__lte=512 * 1024),
                name="named_file_bounded_size",
            ),
            models.CheckConstraint(condition=models.Q(sha256_hash__regex=r"^[0-9a-f]{64}$"), name="named_file_sha256"),
            models.CheckConstraint(
                condition=models.Q(storage_deleted_at__isnull=True) | models.Q(deleted_at__isnull=False),
                name="named_file_cleanup_requires_retirement",
            ),
            models.UniqueConstraint(
                fields=["asset_uuid"], condition=models.Q(deleted_at__isnull=True), name="uq_named_file_active_uuid"
            ),
            models.UniqueConstraint(
                models.F("owner_principal_uuid"),
                models.F("scope_kind"),
                models.F("account_uuid"),
                Coalesce("organization_uuid", models.Value(UUID(int=0))),
                Coalesce("workspace_uuid", models.Value(UUID(int=0))),
                models.F("name"),
                condition=models.Q(deleted_at__isnull=True),
                name="uq_named_file_owner_scope_name",
            ),
        ]


class FileAssetUse(RecordedAuthorityFields):
    """Retain an admitted version until its owning CMS range is destroyed."""

    file_asset = models.ForeignKey(NamedFileAsset, on_delete=models.PROTECT, related_name="uses")
    range_instance = models.ForeignKey("cms.RangeInstance", on_delete=models.CASCADE, related_name="file_inputs")
    input_name = models.CharField(max_length=128, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Each range keeps one immutable selection per declared input name."""

        constraints = [
            models.UniqueConstraint(fields=["range_instance", "input_name"], name="uq_range_named_file_input")
        ]

    def __str__(self) -> str:
        return f"{self.range_instance_id}:{self.input_name}"
