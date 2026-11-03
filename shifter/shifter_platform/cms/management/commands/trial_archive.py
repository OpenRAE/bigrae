"""Authenticated management adapter for the central tenant archive service."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cms.services import (
    configure_trial_archive_destination,
    intake_trial_archive,
    list_trial_archives,
    purge_trial_archives,
    retrieve_trial_archive,
)
from shared.api_tokens.cli import credential_from_file
from shared.credentials import CredentialContext
from shared.exceptions import CMSError, ValidationError
from shared.raes.trial_archive import MAX_ARCHIVE_BYTES, TrialArchiveIdentity


class Command(BaseCommand):
    """Use actual bearer proof and the same service as future dispatchers."""

    help = "Configure, intake, list, retrieve or purge trial archives in approved tenant storage."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare authenticated custody operations and their explicit inputs."""
        parser.add_argument("operation", choices=["configure", "intake", "list", "retrieve", "purge"])
        parser.add_argument("--credential-file", required=True)
        parser.add_argument("--organization", required=True, type=UUID)
        parser.add_argument("--bucket")
        parser.add_argument("--prefix")
        retention = parser.add_mutually_exclusive_group()
        retention.add_argument("--retention-days", type=int)
        retention.add_argument("--keep-indefinitely", action="store_true")
        parser.add_argument("--archive")
        parser.add_argument("--receipt", type=UUID)
        parser.add_argument("--output")
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int, default=100)
        for name in ("experiment", "plan", "entry", "run", "attempt"):
            parser.add_argument(f"--{name}")
        for name in ("plan-digest", "entry-digest", "run-version"):
            parser.add_argument(f"--{name}")

    def handle(self, *args: object, **options: object) -> None:
        """Run one custody operation with body-free errors and metadata output."""
        try:
            credential = credential_from_file(options["credential_file"])
            result = self._execute(credential, options)
        except (CMSError, ValidationError, ValueError, TypeError, OSError):
            raise CommandError(
                "Trial archive operation failed; retain worker evidence and inspect authorized collection status"
            ) from None
        self.stdout.write(json.dumps(result, default=str, sort_keys=True))

    def _execute(self, credential: CredentialContext, options: dict) -> dict | list:
        organization = options["organization"]
        match options["operation"]:
            case "configure":
                if (
                    not options["bucket"]
                    or not options["prefix"]
                    or (options["retention_days"] is None and not options["keep_indefinitely"])
                ):
                    raise ValueError("Explicit destination and retention required")
                configure_trial_archive_destination(
                    credential,
                    organization,
                    bucket=options["bucket"],
                    prefix=options["prefix"],
                    retention_days=options["retention_days"],
                )
                result = {"configured": True}
            case "intake":
                identity = TrialArchiveIdentity(
                    **{f"{name}_id": options[name] for name in ("experiment", "plan", "entry", "run", "attempt")},
                    plan_digest=options["plan_digest"],
                    entry_digest=options["entry_digest"],
                    run_version=options["run_version"],
                )
                if not options["archive"]:
                    raise ValueError("Archive required")
                descriptor = os.open(options["archive"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_ARCHIVE_BYTES:
                        raise ValueError("Bounded regular archive required")
                    result = asdict(intake_trial_archive(credential, organization, identity, source))
            case "list":
                result = [
                    asdict(row)
                    for row in list_trial_archives(
                        credential, organization, offset=options["offset"], limit=options["limit"]
                    )
                ]
            case "retrieve":
                if not options["receipt"] or not options["output"]:
                    raise ValueError("Receipt and output required")
                retrieve_trial_archive(credential, organization, options["receipt"], Path(options["output"]))
                result = {"retrieved": True, "receipt": options["receipt"]}
            case "purge":
                result = {"purged": purge_trial_archives(credential, organization, limit=options["limit"])}
        return result
