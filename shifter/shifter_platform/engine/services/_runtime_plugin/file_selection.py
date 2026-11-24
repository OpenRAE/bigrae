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


def assert_file_selection(
    scope: RuntimePluginScope, binding: RuntimePluginPackBinding | None, installation: RuntimePluginInstallation | None
) -> None:
    """Fence an admitted selection, including deletion before native creation."""
    if binding is None or installation is None:
        if scope.binding_digest is not None or scope.files:
            raise ValidationError("The pack's runtime plugin changed during launch; retry the launch")
        return
    if scope.binding_digest is not None and file_selection_digest(binding, installation) != scope.binding_digest:
        raise ValidationError("The pack's runtime plugin changed during launch; retry the launch")


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
        assert_file_selection(scope, None, None)
        return None, {}
    try:
        manifest = PluginManifest.model_validate(row.installation.manifest)
        bindings = PluginTargetBindings.model_validate(row.bindings)
        bindings.validate_manifest(manifest)
        if (
            row.pack_digest != scope.pack_digest
            or not row.enabled
            or row.installation.state != "ready"
            or manifest.digest != row.installation.manifest_digest
        ):
            raise ValueError("File selection is unavailable")
        assert_file_selection(scope, row, row.installation)
        return file_selection_digest(row, row.installation), dict(bindings.file_assets)
    except ValueError:
        raise ValidationError("The adapter's required file selection is unavailable") from None
