"""Authenticated management adapter for the central tenant archive service."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict, cast
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


class _CommandOptions(TypedDict):
    """Values supplied by the command's declared argument parser."""

    operation: str
    organization: UUID
    bucket: str | None
    prefix: str | None
    retention_days: int | None
    keep_indefinitely: bool
    archive: str | None
    receipt: UUID | None
    output: str | None
    offset: int
    limit: int
    experiment: str | None
    plan: str | None
    entry: str | None
    run: str | None
    attempt: str | None
    plan_digest: str | None
    entry_digest: str | None
    run_version: str | None


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
            proof_file = options["credential_file"]
            if not isinstance(proof_file, (str, Path)):
                raise ValueError("Credential file path required")
            credential = credential_from_file(proof_file)
            result = self._execute(credential, cast(_CommandOptions, options))
        except (CMSError, ValidationError, ValueError, TypeError, OSError):
            raise CommandError(
                "Trial archive operation failed; retain worker evidence and inspect authorized collection status"
            ) from None
        self.stdout.write(json.dumps(result, default=str, sort_keys=True))

    def _execute(
        self, credential: CredentialContext, options: _CommandOptions
    ) -> dict[str, object] | list[dict[str, object]]:
        """Dispatch one authenticated operation using parsed command values."""
        result: dict[str, object] | list[dict[str, object]]
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
                    experiment_id=_identity_argument(options["experiment"]),
                    plan_id=_identity_argument(options["plan"]),
                    entry_id=_identity_argument(options["entry"]),
                    run_id=_identity_argument(options["run"]),
                    attempt_id=_identity_argument(options["attempt"]),
                    plan_digest=_identity_argument(options["plan_digest"]),
                    entry_digest=_identity_argument(options["entry_digest"]),
                    run_version=_identity_argument(options["run_version"]),
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


def _identity_argument(value: str | None) -> str:
    """Require each independently expected identity from the parsed command."""
    if value is None:
        raise ValueError("Expected archive identity required")
    return value
