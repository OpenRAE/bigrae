"""Fixed product management routes served by the persistent native worker."""

from django.urls import path

from ctf.api.participant_control import (
    ParticipantControlBindingView,
    ParticipantControlCommandView,
    ParticipantControlRetryView,
    ParticipantControlStateView,
)

urlpatterns = [
    path(
        "ctf/participants/<uuid:participant_id>/binding/",
        ParticipantControlBindingView.as_view(),
        name="participant-control-bind",
    ),
    path("ctf/bindings/<uuid:binding_id>/", ParticipantControlStateView.as_view(), name="participant-control-state"),
    path(
        "ctf/bindings/<uuid:binding_id>/commands/<uuid:command_id>/retry/",
        ParticipantControlRetryView.as_view(),
        name="participant-control-retry",
    ),
    path(
        "ctf/bindings/<uuid:binding_id>/commands/",
        ParticipantControlCommandView.as_view(),
        name="participant-control-command",
    ),
]
