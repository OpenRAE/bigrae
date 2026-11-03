"""Installation administrators assign existing GCP projects to organizations."""

from dataclasses import asdict
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from engine.services import (
    disable_gcp_range_project,
    list_gcp_range_projects,
    register_gcp_range_project,
    retry_gcp_range_project,
)
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import authenticated_credential
from shared.exceptions import ValidationError

from .preparation_adapters import PreparationSerializer


class ProjectRegistrationSerializer(PreparationSerializer):
    """The operator chooses only an existing project and its organization."""

    organization_uuid = serializers.UUIDField()
    project_id = serializers.RegexField(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$", max_length=30)


class RegisteredProjectSerializer(serializers.Serializer):
    """No baseline metadata, artifact locators or credentials are exposed."""

    id = serializers.UUIDField()
    organization_uuid = serializers.UUIDField()
    project_id = serializers.CharField()
    project_number = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=["pending", "ready", "failed", "disabled"])
    failure_code = serializers.CharField(allow_blank=True)
    in_use = serializers.BooleanField()


class ProjectPageSerializer(serializers.Serializer):
    """Bounded administrative inventory."""

    results = RegisteredProjectSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class ProjectCursorSerializer(PreparationSerializer):
    """Only one opaque continuation identity is accepted."""

    cursor = serializers.UUIDField(required=False)


def _error(request: Request, exc: PermissionError | ValidationError) -> Response:
    """Keep scope and provider diagnostics outside the HTTP boundary."""
    denied = isinstance(exc, PermissionError)
    return api_error_response(
        code="project_access_denied" if denied else "project_invalid",
        message=exc.message if isinstance(exc, ValidationError) else "Project administration is not permitted",
        status_code=403 if denied else 400,
        request=request,
    )


class GcpRangeProjectListCreateView(APIView):
    """Queue registration and inspect status through installation authority."""

    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(parameters=[OpenApiParameter("cursor", type=UUID)], responses=ProjectPageSerializer)
    def get(self, request: Request) -> Response:
        """List one authorized page without provider inventory or credentials."""
        query = ProjectCursorSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            rows, cursor = list_gcp_range_projects(authenticated_credential(request), **query.validated_data)
        except (PermissionError, ValidationError) as exc:
            return _error(request, exc)
        return Response({"results": [asdict(row) for row in rows], "next_cursor": cursor})

    @extend_schema(request=ProjectRegistrationSerializer, responses={202: RegisteredProjectSerializer})
    def post(self, request: Request) -> Response:
        """Queue metadata capture for the operator-selected existing project."""
        body = ProjectRegistrationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            row = register_gcp_range_project(authenticated_credential(request), **body.validated_data)
        except (PermissionError, ValidationError) as exc:
            return _error(request, exc)
        return Response(asdict(row), status=202)


class GcpRangeProjectDisableView(APIView):
    """Prevent allocation while retaining every existing range's project custody."""

    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(request=PreparationSerializer, responses=RegisteredProjectSerializer)
    def post(self, request: Request, registration_id: UUID) -> Response:
        """Fence new allocations while retaining existing range custody."""
        body = PreparationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            row = disable_gcp_range_project(authenticated_credential(request), registration_id)
        except (PermissionError, ValidationError) as exc:
            return _error(request, exc)
        return Response(asdict(row))


class GcpRangeProjectRetryView(APIView):
    """Capture a never-accepted baseline, or independently verify the original one."""

    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(request=PreparationSerializer, responses={202: RegisteredProjectSerializer})
    def post(self, request: Request, registration_id: UUID) -> Response:
        """Queue capture or original-baseline verification with current authority."""
        body = PreparationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            row = retry_gcp_range_project(authenticated_credential(request), registration_id)
        except (PermissionError, ValidationError) as exc:
            return _error(request, exc)
        return Response(asdict(row), status=202)
