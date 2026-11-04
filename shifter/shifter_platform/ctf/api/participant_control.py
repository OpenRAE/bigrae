"""Authenticated native controller routes on the separately installed persistent worker."""

from collections.abc import Callable
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

import cms.services as cms_service
from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import _credential, _resolve_owned_event
from ctf.api.serializers.participant_control import (
    ControlBindingSerializer,
    ControlCommandSerializer,
    ControlOperationSerializer,
    ControlOptionsSerializer,
    ControlPageSerializer,
    ControlRetrySerializer,
    ControlStateSerializer,
)
from ctf.enums import EventCapability
from ctf.models import CTFParticipant
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens import scopes
from shared.exceptions import CMSError, ValidationError
from shared.native_participant import NativeControlStateView, NativeControlSubmission, NativeControlUnavailable


def _subject(request: Request, subject_id: UUID) -> None:
    try:
        participant = CTFParticipant.objects.only("event_id").get(pk=subject_id, deleted_at__isnull=True)
        _resolve_owned_event(request, participant.event_id, capability=EventCapability.RANGES)
    except ObjectDoesNotExist:
        raise _CtfApiError(code="not_found", message="Participant not found", status_code=404) from None


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except PermissionError:
        raise _CtfApiError(code="forbidden", message="Permission denied", status_code=403) from None
    except NativeControlUnavailable:
        raise _CtfApiError(code="dependency_unavailable", message="Service unavailable", status_code=503) from None
    except (ObjectDoesNotExist, ValidationError, CMSError):
        raise _CtfApiError(code="conflict", message="Invalid participant request.", status_code=409) from None
    except ValueError:
        raise _CtfApiError(code="conflict", message="Invalid participant request.", status_code=409) from None
    except Exception:  # noqa: BLE001  # private source, SDK, workload and provider diagnostics never enter responses
        raise _CtfApiError(code="dependency_unavailable", message="Service unavailable", status_code=503) from None


def _state(view: NativeControlStateView) -> dict[str, object]:
    payload = {
        "binding_id": view.binding.id,
        "configuration_id": view.binding.configuration_id,
        "range_uuid": view.binding.range_uuid,
        "episode_id": view.cursor.episode_id,
        "state_revision": view.cursor.state_revision,
        "history_head": view.cursor.history_head,
        "control_cut_digest": view.cursor.control_cut_digest,
        "range_status": view.range_status,
        "commands": view.commands,
        "next_before": view.next_before,
    }
    return dict(ControlStateSerializer(payload).data)


@method_decorator(never_cache, name="dispatch")
class _ControlView(APIView):
    permission_classes = CTF_ORGANIZER_PERMISSIONS
    parser_classes = [ClosedJSONParser]
    required_read_scopes = (scopes.CTF_EVENT_READ,)
    required_write_scopes = (scopes.CTF_EVENT_WRITE,)


class ParticipantControlBindingView(_ControlView):
    """Explicitly bind an organization's installed mapping to the actual current assignment."""

    @extend_schema(responses=ControlOptionsSerializer)
    def get(self, request: Request, participant_id: UUID) -> Response:
        """Discover opaque control choices under current participant custody."""
        try:
            _subject(request, participant_id)
            result = _call(
                lambda: cms_service.native_participant_control_options(
                    _credential(request),
                    product="ctf",
                    subject_uuid=participant_id,
                )
            )
            return Response(ControlOptionsSerializer(result).data)
        except _CtfApiError as error:
            return error.to_response(request)

    @extend_schema(request=ControlBindingSerializer, responses={201: ControlStateSerializer})
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Activate an existing mapping for the current assigned generation."""
        serializer = ControlBindingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _subject(request, participant_id)
            result = _call(
                lambda: cms_service.activate_native_participant_control(
                    _credential(request),
                    product="ctf",
                    subject_uuid=participant_id,
                    configuration_id=serializer.validated_data["configuration_id"],
                )
            )
            return Response(_state(result), status=201)
        except _CtfApiError as error:
            return error.to_response(request)


class ParticipantControlStateView(_ControlView):
    """Authorized bounded references; no full runtime snapshot or private compiler data."""

    @extend_schema(parameters=[ControlPageSerializer], responses=ControlStateSerializer)
    def get(self, request: Request, binding_id: UUID) -> Response:
        """Read a bounded reference page under current event authorization."""
        query = ControlPageSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            subject = _call(lambda: cms_service.native_control_product_subject(binding_id, product="ctf"))
            _subject(request, subject)
            result = _call(
                lambda: cms_service.read_native_participant_control(
                    _credential(request),
                    binding_id,
                    product="ctf",
                    **query.validated_data,
                )
            )
            return Response(_state(result))
        except _CtfApiError as error:
            return error.to_response(request)


class ParticipantControlCommandView(_ControlView):
    """Submit one original proposal, human decision, cancellation or reviewed action."""

    @extend_schema(request=ControlCommandSerializer, responses=ControlOperationSerializer)
    def post(self, request: Request, binding_id: UUID) -> Response:
        """Submit one closed original request through the installed owner."""
        serializer = ControlCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject = _call(lambda: cms_service.native_control_product_subject(binding_id, product="ctf"))
            _subject(request, subject)
            result = _call(
                lambda: cms_service.submit_native_participant_control(
                    _credential(request),
                    binding_id,
                    product="ctf",
                    submission=NativeControlSubmission(**serializer.validated_data),
                )
            )
            return Response(ControlOperationSerializer(result).data)
        except _CtfApiError as error:
            return error.to_response(request)


class ParticipantControlRetryView(_ControlView):
    """Recover the exact original request after a lost response or owner restart."""

    @extend_schema(request=ControlRetrySerializer, responses=ControlOperationSerializer)
    def post(self, request: Request, binding_id: UUID, command_id: UUID) -> Response:
        """Recover the retained request without accepting replacement fields."""
        serializer = ControlRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subject = _call(lambda: cms_service.native_control_product_subject(binding_id, product="ctf"))
            _subject(request, subject)
            result = _call(
                lambda: cms_service.retry_native_participant_control(
                    _credential(request),
                    binding_id,
                    command_id,
                    product="ctf",
                )
            )
            return Response(ControlOperationSerializer(result).data)
        except _CtfApiError as error:
            return error.to_response(request)
