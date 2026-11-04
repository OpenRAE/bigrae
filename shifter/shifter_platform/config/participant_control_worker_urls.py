"""Only the dedicated worker installs the private workload protocol."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/participant-control/", include("config.participant_control_urls")),
    path("internal/participant-control/invocations/", include("cms.api.participant_control_internal_urls")),
]
