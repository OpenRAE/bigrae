"""Organization administration selects verified logical references, never code."""

from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.services import configure_native_participant_control, read_native_control_configuration
from shared.api.closed_serializer import ClosedSerializer
from shared.api.errors import api_error_response
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens import scopes
from shared.api_tokens.permissions import require_scope
from shared.exceptions import CMSError, ValidationError
from shared.native_participant import NativeControlUnavailable, NativePowerControlSelection
from workspaces.services import OrganizationAuthorizationError

from .permissions import CMS_WRITE_PERMISSIONS, cms_actor_credential


class ControlSelectionSerializer(ClosedSerializer):
    """Five closed logical references from the admitted scenario."""

    participant_address = serializers.CharField(max_length=256)
    controller_address = serializers.CharField(max_length=256)
    pause_action_contract_address = serializers.CharField(max_length=256)
    resume_action_contract_address = serializers.CharField(max_length=256)
    observation_boundary_address = serializers.CharField(max_length=256)


class ControlConfigurationRequestSerializer(ClosedSerializer):
    """Require the displayed package digest and logical selection."""

    expected_package_digest = serializers.RegexField(r"^sha256:[0-9a-f]{64}$", max_length=71)
    selection = ControlSelectionSerializer()


class ControlConfigurationSerializer(serializers.Serializer):
    """Expose verified configuration references without compiler material."""

    id = serializers.UUIDField()
    source_package_digest = serializers.CharField()
    configuration_digest = serializers.CharField()
    raes_version = serializers.CharField()
    structural_report_ref = serializers.CharField()
    selection = ControlSelectionSerializer()


class ControlConfigurationStatusSerializer(serializers.Serializer):
    """Distinguish an absent mapping from one that needs review."""

    configuration = ControlConfigurationSerializer(allow_null=True)
    requires_refresh = serializers.BooleanField()


@method_decorator(never_cache, name="dispatch")
class ControlSourceConfigurationView(APIView):
    """Current organization content authority and exact source revision are mandatory."""

    permission_classes = [
        *CMS_WRITE_PERMISSIONS,
        require_scope(scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE),
    ]
    parser_classes = [ClosedJSONParser]

    def handle_exception(self, exc: Exception) -> Response:
        """Return bounded errors without private source or installation diagnostics."""
        if isinstance(exc, APIException):
            return super().handle_exception(exc)
        if isinstance(exc, (PermissionError, OrganizationAuthorizationError)):
            code, message, status = "forbidden", "Permission denied", 403
        elif isinstance(exc, (ObjectDoesNotExist, ValidationError, CMSError, ValueError)) and not isinstance(
            exc,
            NativeControlUnavailable,
        ):
            code, message, status = "conflict", "Participant control configuration unavailable", 409
        else:
            code, message, status = "dependency_unavailable", "Service unavailable", 503
        return api_error_response(code=code, message=message, status_code=status, request=self.request)

    @extend_schema(responses=ControlConfigurationStatusSerializer)
    def get(self, request: Request, organization_uuid: UUID, scenario_id: str) -> Response:
        """Authorize the organization before projecting its current source mapping."""
        status = read_native_control_configuration(cms_actor_credential(request), organization_uuid, scenario_id)
        return Response(ControlConfigurationStatusSerializer(status).data)

    @extend_schema(request=ControlConfigurationRequestSerializer, responses={201: ControlConfigurationSerializer})
    def post(self, request: Request, organization_uuid: UUID, scenario_id: str) -> Response:
        """Verify the exact source revision before saving the authorized mapping."""
        serializer = ControlConfigurationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        view = configure_native_participant_control(
            cms_actor_credential(request),
            organization_uuid,
            scenario_id,
            expected_package_digest=data["expected_package_digest"],
            selection=NativePowerControlSelection(**data["selection"]),
        )
        return Response(ControlConfigurationSerializer(view).data, status=201)
