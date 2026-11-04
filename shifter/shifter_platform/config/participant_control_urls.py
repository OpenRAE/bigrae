"""Compose owning product routes for the persistent participant-control worker."""

from django.urls import include, path

urlpatterns = [
    path("", include("ctf.api.participant_control_urls")),
    path("", include("cms.api.participant_control_urls")),
]
