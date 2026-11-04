"""Scoped file metadata and the incumbent signed-upload HTTP flow."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from shifter_adapter_sdk.runtime import MAX_FILE_INPUT_BYTES

from cms.services import (
    cancel_file_upload,
    complete_file_upload,
    delete_file_asset,
    initiate_file_upload,
    list_file_assets,
)
from mission_control.api._base import MissionControlAPIView, MissionControlReadAPIView, _validated
from mission_control.api.scope import ResourcePlacementSerializer, resource_placement
from mission_control.api.serializers import SuccessResponseSerializer
from mission_control.api.upload_serializers import UploadInitiateResponseSerializer
from mission_control.api.uploads import UploadCancelView, UploadCompleteView, UploadInitiateView
from shared.api.closed_serializer import ClosedSerializer
from shared.authorization.operations import scope_actions
from shared.credentials import CredentialContext
from shared.schemas.cms_projections import UploadAssetRef, UploadInitiation


class FileUploadInitiateSerializer(ResourcePlacementSerializer):
    """Closed opaque-file metadata; storage and ownership are server-selected."""

    name = serializers.CharField(max_length=100)
    filename = serializers.CharField(max_length=255)
    file_size = serializers.JSONField()
    replaces = serializers.IntegerField(min_value=1, required=False)

    def validate_file_size(self, value: object) -> int:
        """Reject coercion and oversized declarations before issuing any URL."""
        if type(value) is not int or not 0 < value <= MAX_FILE_INPUT_BYTES:
            raise serializers.ValidationError("Choose a nonempty file within the upload limit.")
        return value


class FileUploadTokenSerializer(ClosedSerializer):
    """The signed reference alone selects a retained file-purpose admission."""

    upload_token = serializers.CharField(max_length=16384)


class FileAssetSerializer(serializers.Serializer):
    """Display metadata, with no content, object key, owner or digest."""

    id = serializers.IntegerField()
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    original_filename = serializers.CharField()
    file_size_bytes = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class FileAssetListSerializer(serializers.Serializer):
    """Active files and the same server-owned bound used by upload admission."""

    files = FileAssetSerializer(many=True)
    max_file_size_bytes = serializers.IntegerField()


class FileUploadCompleteSerializer(SuccessResponseSerializer):
    """The new immutable version, not a storage capability."""

    file_id = serializers.IntegerField()
    message = serializers.CharField()


class FileAssetListView(MissionControlReadAPIView):
    """List only files in an explicitly resolved native content scope."""

    required_actions = scope_actions("read_content")

    @extend_schema(
        parameters=[ResourcePlacementSerializer],
        responses=FileAssetListSerializer,
        operation_id="api_v1_mission_control_files_list",
    )
    def get(self, request: Request) -> Response:
        """Return scoped metadata without signed downloads or material."""
        values, error = _validated(self, ResourcePlacementSerializer, request.query_params)
        if error is not None:
            return error
        assert values is not None
        credential = self.actor_credential()
        scope = resource_placement(credential, values)
        return Response(
            {
                "files": list_file_assets(credential, scope=scope),
                "max_file_size_bytes": MAX_FILE_INPUT_BYTES,
            }
        )


class FileAssetDetailView(MissionControlAPIView):
    """Retire a version without changing previously admitted range inputs."""

    required_actions = scope_actions("manage_content")

    @extend_schema(responses=SuccessResponseSerializer, operation_id="api_v1_mission_control_files_delete")
    def delete(self, request: Request, file_id: int) -> Response:
        """Use the actual asset's owning scope, never a caller-supplied parent."""
        delete_file_asset(self.actor_credential(), file_id)
        return Response({"success": True})


class FileUploadInitiateView(UploadInitiateView):
    """Share upload locking and error handling while selecting file purpose."""

    upload_serializer = FileUploadInitiateSerializer

    @extend_schema(
        request=FileUploadInitiateSerializer,
        responses=UploadInitiateResponseSerializer,
        operation_id="api_v1_mission_control_file_upload_initiate",
    )
    def post(self, request: Request) -> Response:
        """Issue the existing bounded upload capability for a file asset."""
        return super().post(request)

    def initiate_asset(self, user: CredentialContext, data: dict[str, Any]) -> UploadInitiation:
        """Resolve native placement, retaining any exact replacement reference."""
        return initiate_file_upload(
            user,
            data["name"],
            data["filename"],
            data["file_size"],
            scope=resource_placement(user, data),
            replaces=data.get("replaces"),
        )


class FileUploadCompleteView(UploadCompleteView):
    """Complete only file admissions using the shared session state machine."""

    upload_serializer = FileUploadTokenSerializer
    response_id_field = "file_id"
    asset_label = "File"

    @extend_schema(
        request=FileUploadTokenSerializer,
        responses=FileUploadCompleteSerializer,
        operation_id="api_v1_mission_control_file_upload_complete",
    )
    def post(self, request: Request) -> Response:
        """Return metadata for the installed immutable version."""
        return super().post(request)

    def complete_asset(self, user: CredentialContext, token: str) -> UploadAssetRef:
        """The file service refuses installer tokens before any provider read."""
        return complete_file_upload(user, token)


class FileUploadCancelView(UploadCancelView):
    """Cancel only file admissions through the shared session cleanup path."""

    upload_serializer = FileUploadTokenSerializer

    @extend_schema(
        request=FileUploadTokenSerializer,
        responses=SuccessResponseSerializer,
        operation_id="api_v1_mission_control_file_upload_cancel",
    )
    def post(self, request: Request) -> Response:
        """Keep exact capability cleanup evidence after cancellation."""
        return super().post(request)

    def cancel_asset(self, user: CredentialContext, token: str) -> None:
        """File-purpose validation remains in the owning CMS service."""
        cancel_file_upload(user, token)
