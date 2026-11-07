"""Run a retained experiment batch on disposable workers."""

from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cms.services import (
    list_experiment_entries,
    reconcile_experiment_dispatch,
    start_experiment_dispatch,
    stop_experiment_dispatch,
)
from shared.api_tokens.cli import credential_from_file
from shared.exceptions import CMSError
from workspaces.services import hierarchy_target_scope


class Command(BaseCommand):
    help = "Start, show, stop, collect, or reconcile a retained experiment batch on disposable workers."

    def add_arguments(self, parser: CommandParser) -> None:
        """Accept a credential file, batch selectors and the worker scope."""
        parser.add_argument("operation", choices=["start", "show", "stop", "collect", "reconcile"])
        parser.add_argument("--credential-file", required=True)
        parser.add_argument("--organization", type=UUID, required=True)
        parser.add_argument("--batch", type=UUID, required=True)
        parser.add_argument("--scope-kind", choices=("account", "organization", "workspace"))
        parser.add_argument("--scope-id", type=UUID)

    def handle(self, *args: object, **options: object) -> None:
        """Run one operation and print one JSON line per entry."""
        operation = str(options["operation"])
        try:
            credential = credential_from_file(str(options["credential_file"]))
            organization, batch = UUID(str(options["organization"])), UUID(str(options["batch"]))
            if operation == "show":
                rows = list_experiment_entries(credential, organization, batch)
            elif operation == "stop":
                rows = [asdict(step) for step in stop_experiment_dispatch(credential, organization, batch)]
            else:
                if not options.get("scope_kind") or not options.get("scope_id"):
                    raise ValueError("Worker scope required")
                scope = hierarchy_target_scope(str(options["scope_kind"]), UUID(str(options["scope_id"])))
                if operation == "start":
                    steps = start_experiment_dispatch(credential, organization, batch, scope=scope)
                else:
                    steps = reconcile_experiment_dispatch(
                        credential, organization, batch, scope=scope, collect_only=operation == "collect"
                    )
                rows = [asdict(step) for step in steps]
        except (CMSError, ValueError, TypeError, OSError, PermissionError):
            raise CommandError(
                f"Experiment dispatch {operation} failed; verify authority, worker capacity and batch state"
            ) from None
        for row in rows:
            self.stdout.write(json.dumps(row, sort_keys=True))
