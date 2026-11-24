"""Canonical DRF views for the CTF JSON API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import _canonical_error_response
from ctf.api.serializers import PublicScoreboardQuerySerializer, PublicScoreboardResponseSerializer
from ctf.enums import ScoreboardKind

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEvent


def _scoreboard_access_allowed(event: CTFEvent, request: Request) -> bool:
    """Public publication stays public; restricted reads require native admission."""
    from ctf.enums import ScoreboardVisibility
    from ctf.exceptions import CTFPermissionError
    from ctf.services.event_projection import authorize_event_projection
    from shared.api.principals import authenticated_credential

    if event.scoreboard_visibility != ScoreboardVisibility.PARTICIPANTS.value:
        return event.scoreboard_visibility == ScoreboardVisibility.PUBLIC.value
    try:
        credential = authenticated_credential(request)
        authorize_event_projection(credential, event.pk)
        return True
    except (ValueError, CTFPermissionError):
        return False


class _KindRejectedError(Exception):
    """A rejected ``kind`` selector, carrying its authored public error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def _selected_kind(event: CTFEvent, request: Request) -> ScoreboardKind:
    """Resolve the board to read; an absent selector keeps the event default (#2968)."""
    values = request.query_params.getlist("kind")
    if not values:
        return ScoreboardKind.TEAM if event.team_mode else ScoreboardKind.INDIVIDUAL
    query = PublicScoreboardQuerySerializer(data={"kind": values[0]})
    if len(values) > 1 or not query.is_valid():
        raise _KindRejectedError("invalid_scoreboard_kind", "Invalid scoreboard kind")
    kind = ScoreboardKind(query.validated_data["kind"])
    if kind is ScoreboardKind.TEAM and not event.team_mode:
        raise _KindRejectedError("scoreboard_kind_unavailable", "This event has no team scoreboard")
    return kind


class PublicScoreboardView(APIView):
    """Public event scoreboard read surface."""

    versioning_class = None
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[PublicScoreboardQuerySerializer], responses=PublicScoreboardResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> JsonResponse | Response:
        """Return the public scoreboard payload for an event."""
        from ctf.exceptions import CTFError, CTFNotFoundError
        from ctf.services import get_event
        from shared.api.errors import api_error_response

        try:
            event = get_event(event_id)
        except CTFNotFoundError:
            response = JsonResponse({"error": "Event not found"}, status=404)
            return _canonical_error_response(request, response) or response

        try:
            kind = _selected_kind(event, request)
            allowed = _scoreboard_access_allowed(event, request)
        except _KindRejectedError as rejected:
            result = api_error_response(request=request, code=rejected.code, message=rejected.message, status_code=400)
        except CTFError:
            result = api_error_response(
                request=request, code="scoreboard_unavailable", message="Scoreboard unavailable", status_code=503
            )
        else:
            result = _scoreboard_payload(event, request, allowed, kind)
        return result


def _scoreboard_payload(event: CTFEvent, request: Request, allowed: bool, kind: ScoreboardKind) -> JsonResponse:
    """Project admitted rankings or the published empty scoreboard shape."""
    from ctf.services.scoring import get_score_progression, get_scoreboard, get_team_scoreboard
    from ctf.views import _parsing

    if not allowed:
        return JsonResponse(
            {
                "scoreboard_hidden": True,
                "event_id": str(event.id),
                "team_mode": event.team_mode,
                "frozen": event.is_scoreboard_frozen,
                "rankings": [],
                "bracket_rankings": None,
                "brackets": [],
                "progression": None,
            }
        )

    freeze_at = event.scoreboard_freeze_at if event.is_scoreboard_frozen else None
    bracket_param = request.query_params.get("bracket")
    brackets, _selected_bracket, bracket_id = _parsing._resolve_bracket_filter(event.id, bracket_param)
    team = kind is ScoreboardKind.TEAM
    read_board = get_team_scoreboard if team else get_scoreboard
    rankings = read_board(event.id, freeze_at=freeze_at)
    bracket_rankings = read_board(event.id, freeze_at=freeze_at, bracket_id=bracket_id) if bracket_id else None
    progression = get_score_progression(
        event,
        rankings if bracket_rankings is None else bracket_rankings,
        team=team,
        freeze_at=freeze_at,
        bracket_id=bracket_id,
    )

    return JsonResponse(
        {
            "scoreboard_hidden": False,
            "event_id": str(event.id),
            "team_mode": event.team_mode,
            "frozen": event.is_scoreboard_frozen,
            "rankings": rankings,
            "bracket_rankings": bracket_rankings,
            "brackets": [{"id": str(bracket.id), "name": bracket.name} for bracket in brackets],
            "progression": progression,
        }
    )


api_scoreboard = PublicScoreboardView.as_view()

__all__ = [
    "api_scoreboard",
]
