"""Organizer captain assignment without participant invite-secret disclosure."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError, ctf_error_response
from ctf.api.organizer._audit import audit_admin_event_mutation
from ctf.api.organizer._base import _EVENT_WRITE, _credential, _raise_not_found, _resolve_owned_event
from ctf.api.serializers import TeamMemberRequestSerializer
from ctf.exceptions import CTFError


class OrganizerCaptainSerializer(serializers.Serializer):
    """Minimal team identity and current captain; no invitation material."""

    id = serializers.UUIDField(read_only=True)
    captain_id = serializers.UUIDField(read_only=True, allow_null=True)


class TeamCaptainView(APIView):
    """Reassign an existing team's captain using event team authority."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=TeamMemberRequestSerializer, responses=OrganizerCaptainSerializer)
    @audit_admin_event_mutation("team.reassign_captain")
    def post(self, request: Request, team_id: UUID) -> Response:
        """Authorize the event and assign the requested teammate as captain."""
        from ctf.models import CTFTeam
        from ctf.services.team import reassign_captain

        try:
            team = CTFTeam.objects.filter(pk=team_id).first()
            if team is None:
                _raise_not_found("Team not found.")
            _resolve_owned_event(request, team.event_id, capability="teams")
            serializer = TeamMemberRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            team = reassign_captain(team.pk, serializer.validated_data["participant_id"], actor=_credential(request))
            return Response(OrganizerCaptainSerializer(team).data)
        except _CtfApiError as exc:
            return exc.to_response(request)
        except CTFError as exc:
            return ctf_error_response(request, exc)
