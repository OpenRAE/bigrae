"""Resolve configured project facts for read-only catalog assessment."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from engine.services import runtime_plugin_plan_parameters
from shared.exceptions import ValidationError
from shared.raes.project_parameters import required_project_parameters, select_project_parameters
from shared.raes.realizability import GapCategory, RealizabilityGap
from shared.runtime_plugin_binding import RuntimePluginScope

if TYPE_CHECKING:
    from cms.models import RaesPackageSource
    from shared.identity_scope import ResourceScope

_CONFIGURATION_REQUIRED = "Target configuration required"


def configured_project_parameters(
    path: Path, source: RaesPackageSource, scope: ResourceScope | None
) -> dict[str, object] | None:
    """Keep unsupported source parameters separate from missing project settings."""
    parameters = None
    if required_project_parameters(path):
        organization_uuid = source.organization_uuid or (scope.organization_uuid if scope else None)
        try:
            if organization_uuid is None:
                raise ValueError(_CONFIGURATION_REQUIRED)
            _, facts = runtime_plugin_plan_parameters(
                RuntimePluginScope(
                    organization_uuid=organization_uuid, pack_id=source.scenario_id, pack_digest=source.package_digest
                )
            )
            if not facts:
                raise ValueError(_CONFIGURATION_REQUIRED)
            parameters = select_project_parameters(path, facts)
        except (ValueError, ValidationError):
            raise ValidationError(_CONFIGURATION_REQUIRED) from None
    return parameters


def target_configuration_gap() -> RealizabilityGap:
    """Expose an actionable setting without exposing project values."""
    return RealizabilityGap(
        code="shifter-realizability.target-configuration-required",
        address="plan",
        category=GapCategory.TARGET,
        message="Select a ready registered target project in the pack's adapter settings",
    )
