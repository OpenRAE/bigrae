"""Read an exact administrator selection before CMS admits private file inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from shifter_adapter_sdk.runtime import PluginManifest, canonical_digest

from shared.exceptions import ValidationError
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginScope

if TYPE_CHECKING:
    from engine.models import RuntimePluginInstallation, RuntimePluginPackBinding


def file_selection_digest(binding: RuntimePluginPackBinding, installation: RuntimePluginInstallation) -> str:
    """Bind the exact stored selection without normalizing historical JSON."""
    return canonical_digest(
        {
            "installation_id": str(binding.installation_id),
            "manifest_digest": installation.manifest_digest,
            "pack_digest": binding.pack_digest,
            "bindings": binding.bindings,
            "enabled": binding.enabled,
        }
    )


def runtime_plugin_file_selection(scope: RuntimePluginScope) -> tuple[str | None, dict[str, UUID]]:
    """Called only after CMS authorizes the source and its actual launch scope."""
    from engine.models import RuntimePluginPackBinding

    row = (
        RuntimePluginPackBinding.objects.select_related("installation")
        .filter(
            organization_uuid=scope.organization_uuid,
            pack_id=scope.pack_id,
        )
        .first()
    )
    if row is None:
        return None, {}
    try:
        manifest = PluginManifest.model_validate(row.installation.manifest)
        bindings = PluginTargetBindings.model_validate(row.bindings)
        bindings.validate_manifest(manifest)
        if not manifest.required_files:
            return None, {}
        if (
            row.pack_digest != scope.pack_digest
            or not row.enabled
            or row.installation.state != "ready"
            or manifest.digest != row.installation.manifest_digest
        ):
            raise ValueError("File selection is unavailable")
        return file_selection_digest(row, row.installation), dict(bindings.file_assets)
    except ValueError:
        raise ValidationError("The adapter's required file selection is unavailable") from None
