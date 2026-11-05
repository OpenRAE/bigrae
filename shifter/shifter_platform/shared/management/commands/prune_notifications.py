"""Prune expired WebSocket notification queue rows.

The Helm CronJob runs this command on a schedule (ADR-072-R5). Each run deletes
at most ``--batch-size * --max-batches`` rows, so it is safe to run twice.
"""

from __future__ import annotations

from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from shared.notifications import prune_expired_notifications


class Command(BaseCommand):
    """Delete expired shared WebSocket notifications."""

    help = "Delete expired shared WebSocket notification queue rows in bounded batches."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Bound the delete work of one run."""
        parser.add_argument("--batch-size", type=int, default=1000, help="Max rows deleted per batch")
        parser.add_argument("--max-batches", type=int, default=100, help="Max batches per run")

    def handle(self, *args, **options) -> None:
        """Run notification queue pruning."""
        deleted = prune_expired_notifications(batch_size=options["batch_size"], max_batches=options["max_batches"])
        suffix = "" if deleted == 1 else "s"
        self.stdout.write(f"Deleted {deleted} expired WebSocket notification{suffix}.")
