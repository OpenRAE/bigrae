"""Fixed private HTTPS protocol; native Job tokens never borrow browser authentication."""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from pydantic import SecretStr
from rest_framework import serializers
from rest_framework.authentication import get_authorization_header
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.services._participant_control_invocations import (
    begin_native_participant_invocation,
    finish_native_participant_invocation,
    withdraw_native_participant_invocation,
)
from shared.api.closed_serializer import ClosedSerializer
from shared.api.errors import api_error_response
from shared.api.strict_json import ClosedJSONParser
from shared.native_power_protocol import native_power_grant_payload


class _BeginSerializer(ClosedSerializer):
    operation_id = serializers.UUIDField()
    member_ref = serializers.CharField(min_length=1, max_length=512)
    attempt_id = serializers.UUIDField()


class _FinishSerializer(ClosedSerializer):
    invocation_id = serializers.UUIDField()
    attempt_id = serializers.UUIDField()


def _token(request: Request) -> SecretStr:
    header = get_authorization_header(request)
    parts = header.split()
    if len(header) > 16_384 or len(parts) != 2 or parts[0].lower() != b"bearer":
        raise ValueError("Native workload authentication unavailable")
    return SecretStr(parts[1].decode("ascii"))


@method_decorator(never_cache, name="dispatch")
class _WorkloadView(APIView):
    # Engine validates an explicit-audience TokenReview and the live Pod/Job
    # before any grant. Session cookies and platform bearer tokens supply no
    # permission on this private machine protocol.
    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [ClosedJSONParser]
    schema = None


class NativeInvocationBeginView(_WorkloadView):
    """Acquire one native grant through the private workload boundary."""

    def post(self, request: Request) -> Response:
        """Authenticate the actual workload before admitting its original attempt."""
        serializer = _BeginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            grant = begin_native_participant_invocation(token=_token(request), **serializer.validated_data)
            return Response(native_power_grant_payload(grant))
        except Exception:  # noqa: BLE001  # no native existence, private source or provider faults cross this boundary
            return api_error_response(code="forbidden", message="Permission denied", status_code=403, request=request)


class NativeInvocationFinishView(_WorkloadView):
    """Record cessation of the exact authenticated invocation."""

    def post(self, request: Request) -> Response:
        """Close only the original workload attempt without borrowing actor authority."""
        serializer = _FinishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            finish_native_participant_invocation(token=_token(request), **serializer.validated_data)
            return Response(status=204)
        except Exception:  # noqa: BLE001  # unknown completion retains native exclusion
            return api_error_response(code="forbidden", message="Permission denied", status_code=403, request=request)


class NativeInvocationWithdrawView(_WorkloadView):
    """Fence a workload attempt that has not called the provider."""

    def post(self, request: Request) -> Response:
        """Retain exclusion unless the original no-call attempt is authenticated."""
        serializer = _BeginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            withdraw_native_participant_invocation(token=_token(request), **serializer.validated_data)
            return Response(status=204)
        except Exception:  # noqa: BLE001  # failed withdrawal retains exclusion; no private cause leaves the protocol
            return api_error_response(code="forbidden", message="Permission denied", status_code=403, request=request)
