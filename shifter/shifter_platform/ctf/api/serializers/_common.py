"""Shared building-block serializers for the canonical CTF DRF API."""

from __future__ import annotations

from rest_framework import serializers


class _NamedRefSerializer(serializers.Serializer):
    """A minimal ``{id, name}`` reference to a related entity."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class ChallengeFirstBloodSerializer(serializers.Serializer):
    """The first solver shown in challenge statistics (display name only)."""

    participant_name = serializers.CharField(read_only=True)
    time = serializers.CharField(read_only=True)


class ChallengeStatisticsSerializer(serializers.Serializer):
    """Per-challenge statistics shared by the participant and organizer detail (CTF-407).

    Organizers always receive this. Participants receive it only when the event
    enables it; otherwise the challenge detail carries ``statistics: null``.
    """

    challenge_id = serializers.CharField(read_only=True)
    total_attempts = serializers.IntegerField(read_only=True)
    solve_count = serializers.IntegerField(read_only=True)
    solve_rate = serializers.FloatField(read_only=True)
    first_blood = ChallengeFirstBloodSerializer(read_only=True, allow_null=True)
