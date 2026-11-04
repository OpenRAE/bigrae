"""Fixed source configuration routes; only registered source identity is supplied."""

from django.urls import path

from cms.api.participant_control_configuration import ControlSourceConfigurationView

urlpatterns = [
    path(
        "organizations/<uuid:organization_uuid>/sources/<str:scenario_id>/",
        ControlSourceConfigurationView.as_view(),
        name="participant-control-source",
    ),
]
