"""Closed native management inputs; no SDK intents, policy gates or provider selectors."""

from rest_framework import serializers

from shared.api.closed_serializer import ClosedSerializer


class ControlBindingSerializer(ClosedSerializer):
    """Select only an existing verified configuration."""

    configuration_id = serializers.UUIDField()


class ControlOptionsSerializer(serializers.Serializer):
    """Return opaque discovery references and mapping freshness."""

    configuration_id = serializers.UUIDField(allow_null=True)
    binding_id = serializers.UUIDField(allow_null=True)
    requires_refresh = serializers.BooleanField()


class ControlCommandSerializer(ClosedSerializer):
    """Describe a native request without accepting portable verdicts or code."""

    request_id = serializers.UUIDField()
    kind = serializers.ChoiceField(
        choices=["proposal", "approval", "denial", "cancellation", "action"],
        error_messages={"invalid_choice": "Unsupported participant control command."},
    )
    verb = serializers.ChoiceField(
        choices=["pause", "resume"],
        error_messages={"invalid_choice": "Unsupported power operation."},
    )
    proposal_id = serializers.UUIDField()
    action_id = serializers.UUIDField()
    expected_cut_digest = serializers.RegexField(r"^sha256:[0-9a-f]{64}$", max_length=71)
    decision_id = serializers.UUIDField(required=False, allow_null=True)


class ControlPageSerializer(ClosedSerializer):
    """Bound history navigation to one retained command reference."""

    before = serializers.UUIDField(required=False)


class ControlRetrySerializer(ClosedSerializer):
    """Retry only the server's retained original request; no replacement fields."""


class ControlOperationSerializer(serializers.Serializer):
    """Project the owning SDK receipt separately from native power truth."""

    command_id = serializers.UUIDField()
    operation_id = serializers.UUIDField()
    state = serializers.CharField()


class ControlCommandReferenceSerializer(serializers.Serializer):
    """Expose body-free original command and receipt references."""

    id = serializers.UUIDField()
    kind = serializers.CharField()
    verb = serializers.CharField()
    proposal_id = serializers.UUIDField()
    action_id = serializers.UUIDField()
    operation_id = serializers.UUIDField(allow_null=True)
    operation_state = serializers.CharField(allow_null=True)


class ControlStateSerializer(serializers.Serializer):
    """Return current coordinates, native status, and a bounded command page."""

    binding_id = serializers.UUIDField()
    configuration_id = serializers.UUIDField()
    range_uuid = serializers.UUIDField()
    episode_id = serializers.CharField()
    state_revision = serializers.IntegerField()
    history_head = serializers.IntegerField()
    control_cut_digest = serializers.CharField()
    range_status = serializers.CharField()
    commands = ControlCommandReferenceSerializer(many=True)
    next_before = serializers.UUIDField(allow_null=True)
