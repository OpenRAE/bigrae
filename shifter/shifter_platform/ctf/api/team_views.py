"""Canonical DRF participant team lifecycle views (CTF-501..506).

POST actions on the actor's own team: create, join by invite code, leave,
and the captain-only rename / regenerate-code / transfer / remove-member /
disband actions. Domain rules (team mode, capacity under the #1140 row lock,
captain authorization) live in :mod:`ctf.services.team`; these views resolve
the acting participant with the same event-scoped policy as the other
``/me/*`` reads and translate the ``CTFError`` family into the shared error
envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.cache import add_never_cache_headers
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api import projections
from ctf.api._base import CTF_PARTICIPANT_PERMISSIONS
from ctf.api._base import ctf_error_response as _ctf_error_response
from ctf.api.participant_views import _resolve_active_participant
from ctf.api.serializers import (
    ParticipantTeamSerializer,
    TeamCreateRequestSerializer,
    TeamJoinRequestSerializer,
    TeamMemberRequestSerializer,
    TeamRegenerateCodeRequestSerializer,
)
from ctf.exceptions import CTFError
from shared.api.errors import api_error_response
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens import scopes

if TYPE_CHECKING:
    from collections.abc import Callable

    from ctf.models import CTFParticipant

_NO_ACTIVE_EVENT = "No active CTF event for this participant."
_PLAY_WRITE = (scopes.CTF_PLAY_WRITE,)


def _no_participant_response(request: Request) -> Response:
    """404 for actors without an active CTF event."""
    return api_error_response(
        code="not_found",
        message=_NO_ACTIVE_EVENT,
        status_code=status.HTTP_404_NOT_FOUND,
        request=request,
    )


def _team_response(participant: CTFParticipant) -> Response:
    """Serialize the participant's refreshed team projection.

    The captain projection carries the invite code, a join secret, so the
    response is never cached (CTF-504).
    """
    participant.refresh_from_db()
    team = projections.participant_team(participant)
    response = Response(ParticipantTeamSerializer(team).data)
    add_never_cache_headers(response)
    return response


class _TeamActionView(APIView):
    """Shared plumbing for participant team POST actions."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    def _act(self, request: Request, action: Callable[[CTFParticipant], object]) -> Response:
        """Resolve the participant, run ``action(participant)``, shape the response."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            action(participant)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return _team_response(participant)


class TeamCreateView(_TeamActionView):
    """Create a team; the creator becomes captain."""

    @extend_schema(request=TeamCreateRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Create a team named by the request body."""
        from ctf.services.team import create_team

        serializer = TeamCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: create_team(p.pk, serializer.validated_data["name"]))


class TeamJoinView(_TeamActionView):
    """Join a team by invite code (capacity-guarded, #1140)."""

    @extend_schema(request=TeamJoinRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Join the team matching the submitted invite code."""
        from ctf.services.team import join_team

        serializer = TeamJoinRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: join_team(p.pk, serializer.validated_data["invite_code"]))


class TeamLeaveView(_TeamActionView):
    """Leave the current team."""

    @extend_schema(request=None, responses=None)
    def post(self, request: Request) -> Response:
        """Leave; a lone captain disbands the team by leaving."""
        from ctf.services.team import leave_team

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            leave_team(participant.pk)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return Response({"left": True})


class TeamRenameView(_TeamActionView):
    """Rename the team (captain only)."""

    @extend_schema(request=TeamCreateRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Rename to the requested unique-per-event name."""
        from ctf.services.team import rename_team

        serializer = TeamCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: rename_team(p.pk, serializer.validated_data["name"]))


class TeamRegenerateCodeView(_TeamActionView):
    """Mint a fresh invite code (captain only), with optional settings."""

    parser_classes = [ClosedJSONParser, FormParser, MultiPartParser]

    @extend_schema(request=TeamRegenerateCodeRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Invalidate the old invite code and return the new one.

        An empty body keeps the current settings. ``single_use`` and
        ``expires_in_seconds`` are optional; an omitted field keeps its value.
        """
        from ctf.services.team import _UNSET, regenerate_invite_code

        serializer = TeamRegenerateCodeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Decide "supplied" from the parsed request, not from validated_data: a
        # non-partial DRF BooleanField coerces an omitted HTML-form field to
        # False, which would silently downgrade a single-use code. A key absent
        # from request.data (JSON or form) means "keep the current value".
        supplied = request.data
        validated = serializer.validated_data
        single_use = validated["single_use"] if "single_use" in supplied else _UNSET
        expires_in_seconds = validated["expires_in_seconds"] if "expires_in_seconds" in supplied else _UNSET
        return self._act(
            request,
            lambda p: regenerate_invite_code(p.pk, single_use=single_use, expires_in_seconds=expires_in_seconds),
        )


class TeamTransferCaptaincyView(_TeamActionView):
    """Hand captaincy to a teammate (captain only)."""

    @extend_schema(request=TeamMemberRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Transfer captaincy to the named teammate."""
        from ctf.services.team import transfer_captaincy

        serializer = TeamMemberRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: transfer_captaincy(p.pk, serializer.validated_data["participant_id"]))


class TeamRemoveMemberView(_TeamActionView):
    """Remove a teammate (captain only)."""

    @extend_schema(request=TeamMemberRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Remove the named teammate from the team."""
        from ctf.services.team import remove_member

        serializer = TeamMemberRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: remove_member(p.pk, serializer.validated_data["participant_id"]))


class TeamDisbandView(_TeamActionView):
    """Dissolve the team (captain only)."""

    @extend_schema(request=None, responses=None)
    def post(self, request: Request) -> Response:
        """Unteam every member and delete the team."""
        from ctf.services.team import disband_team

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            disband_team(participant.pk)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return Response({"disbanded": True})
