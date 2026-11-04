"""Admit optional installed software without creating a content-pack binding."""

from typing import TYPE_CHECKING

from shared.disposable_workers import WorkerHostProfile
from shared.runtime_plugin_binding import RuntimeApparatusPin

if TYPE_CHECKING:
    from engine.models import Range
    from shared.identity_scope import ResourceScope


def pin_worker_software(profile: WorkerHostProfile, runtime: Range, scope: ResourceScope) -> None:
    """Retain the administrator's exact installation under its existing lock."""
    from engine.models import RuntimePluginInstallation

    from ._runtime_plugin_bindings import persist_runtime_plugin_pin

    selected = profile.software
    if selected is None:
        return
    installation = RuntimePluginInstallation.objects.select_for_update().get(pk=selected.installation_id)
    if (
        scope.organization_uuid != selected.organization_uuid
        or installation.organization_uuid != selected.organization_uuid
        or installation.state != "ready"
        or installation.manifest_digest != selected.manifest_digest
    ):
        raise ValueError("Worker software installation is unavailable")
    pin = RuntimeApparatusPin(
        organization_uuid=selected.organization_uuid,
        installation_id=installation.id,
        apparatus_digest=profile.digest,
        manifest=installation.manifest,
        bindings=selected.bindings,
    )
    if pin.manifest.digest != installation.manifest_digest:
        raise ValueError("Worker software identity changed")
    pin.bindings.validate_plan(profile.plan)
    pin.bindings.validate_provider("gce")
    persist_runtime_plugin_pin(runtime, pin)
