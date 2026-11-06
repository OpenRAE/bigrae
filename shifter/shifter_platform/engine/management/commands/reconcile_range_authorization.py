"""Confirm the recorded parent of one previously accepted native range."""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from engine.services import publish_range_relationships


class Command(BaseCommand):
    """Repair one retained range relationship through its owning service."""

    help = "Publish and confirm one native range's retained parent relationship."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--request-id", required=True, type=UUID)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            publish_range_relationships(options["request_id"])
        except ValueError:
            raise CommandError("Range authority publication unavailable") from None
        self.stdout.write("Range parent relationship confirmed")
