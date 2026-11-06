"""Resolve registered project facts under an admitted administrator selection."""

import re

from pydantic import TypeAdapter
from shifter_adapter_sdk.runtime import PluginManifest

from shared.exceptions import ValidationError
from shared.gcp_range_projects import GcpBaselineRef, ProjectID
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginScope

from ._runtime_plugin_file_selection import assert_file_selection, file_selection_digest

_UNAVAILABLE = "The pack's registered target project is unavailable"


def project_parameters_for_binding(scope: RuntimePluginScope, bindings: PluginTargetBindings) -> dict[str, str]:
    """Project facts grant no authority; CMS must authorize the supplied scope first."""
    from engine.models import GcpRangeProject

    project_id = bindings.parameters.get("project-id")
    if project_id is None:
        return {}
    try:
        project_id = TypeAdapter(ProjectID).validate_python(project_id)
        project = GcpRangeProject.objects.filter(
            project_id=project_id, organization_uuid=scope.organization_uuid, status="ready"
        ).first()
        if project is None or not re.fullmatch(r"[1-9]\d{5,19}", project.project_number, flags=re.ASCII):
            raise ValueError(_UNAVAILABLE)
        baseline = GcpBaselineRef.model_validate(project.baseline)
        if baseline.registration_id != project.pk:
            raise ValueError(_UNAVAILABLE)
        return {"project_id": project.project_id, "project_number": project.project_number}
    except ValueError:
        raise ValidationError(_UNAVAILABLE) from None


def runtime_plugin_plan_parameters(scope: RuntimePluginScope) -> tuple[RuntimePluginScope, dict[str, str]]:
    """Capture the exact selection and reuse its existing launch-time digest fence."""
    from engine.models import RuntimePluginPackBinding

    row = (
        RuntimePluginPackBinding.objects.select_related("installation")
        .filter(organization_uuid=scope.organization_uuid, pack_id=scope.pack_id)
        .first()
    )
    if row is None:
        assert_file_selection(scope, None, None)
        return scope, {}
    try:
        installation = row.installation
        manifest = PluginManifest.model_validate(installation.manifest)
        bindings = PluginTargetBindings.model_validate(row.bindings)
        bindings.validate_manifest(manifest)
        if (
            row.pack_digest != scope.pack_digest
            or not row.enabled
            or installation.state != "ready"
            or installation.organization_uuid != scope.organization_uuid
            or manifest.digest != installation.manifest_digest
        ):
            raise ValueError(_UNAVAILABLE)
        assert_file_selection(scope, row, installation)
        captured = scope.model_copy(update={"binding_digest": file_selection_digest(row, installation)})
        return captured, project_parameters_for_binding(captured, bindings)
    except ValueError:
        raise ValidationError(_UNAVAILABLE) from None
