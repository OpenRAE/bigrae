"""Confirm the recorded parent of one previously accepted native range."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from engine.services import publish_range_relationships


class Command(BaseCommand):
    help = "Publish and confirm one native range's retained parent relationship."

    def add_arguments(self, parser):
        parser.add_argument("--request-id", required=True, type=UUID)

    def handle(self, *args, **options):
        try:
            publish_range_relationships(options["request_id"])
        except ValueError:
            raise CommandError("Range authority publication unavailable") from None
        self.stdout.write("Range parent relationship confirmed")
