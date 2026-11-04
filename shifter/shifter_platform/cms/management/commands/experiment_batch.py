"""Admission-only command over the native experiment service facade."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cms.services import admit_experiment_batch, export_experiment_batch, load_experiment_batch
from shared.api_tokens.cli import credential_from_file
from shared.exceptions import CMSError, ValidationError
from shared.raes.experiment_admission import MAX_AUTHORITY_BYTES
from shared.raes.json_ingress import parse_bounded_json_object


class Command(BaseCommand):
    """Retain or inspect exact trial inputs without creating execution resources."""

    help = "Admit an installed pack experiment or show its retained batch metadata; never dispatch."

    def add_arguments(self, parser: CommandParser) -> None:
        """Keep proof transport in the existing private credential-file boundary."""
        parser.add_argument("operation", choices=["admit", "show", "export"])
        parser.add_argument("--credential-file", required=True)
        parser.add_argument("--organization", type=UUID, required=True)
        parser.add_argument("--batch", type=UUID)
        parser.add_argument("--scenario")
        parser.add_argument("--experiment")
        parser.add_argument("--experiment-version")
        parser.add_argument("--apparatus-file")
        parser.add_argument("--concurrency", type=int, default=1)

    def handle(self, *args: object, **options: object) -> None:
        """Authenticate actual proof and emit a body-free summary or fixed refusal."""
        try:
            credential = credential_from_file(str(options["credential_file"]))
            organization = UUID(str(options["organization"]))
            if options["operation"] == "export":
                if options.get("batch") is None:
                    raise ValueError("Batch required")
                exported = export_experiment_batch(credential, organization, UUID(str(options["batch"])))
                self.stdout.write(json.dumps(exported, sort_keys=True))
                return
            if options["operation"] == "show":
                if options.get("batch") is None:
                    raise ValueError("Batch required")
                result = load_experiment_batch(credential, organization, UUID(str(options["batch"])))
            else:
                if not all(options.get(key) for key in ("scenario", "experiment", "apparatus_file")):
                    raise ValueError("Explicit experiment selection and authority required")
                descriptor = os.open(Path(str(options["apparatus_file"])), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_AUTHORITY_BYTES:
                        raise ValueError("Bounded regular authority document required")
                    authority = parse_bounded_json_object(
                        source.read(MAX_AUTHORITY_BYTES + 1), max_bytes=MAX_AUTHORITY_BYTES
                    )
                result = admit_experiment_batch(
                    credential,
                    organization,
                    scenario_id=str(options["scenario"]),
                    experiment_id=str(options["experiment"]),
                    authority=authority,
                    concurrency=int(str(options["concurrency"])),
                    experiment_version=str(options["experiment_version"])
                    if options.get("experiment_version")
                    else None,
                )
        except (CMSError, ValidationError, ValueError, TypeError, OSError):
            raise CommandError(
                "Experiment admission failed; verify authority, installed inputs and resource limits"
            ) from None
        self.stdout.write(json.dumps(result.summary(), sort_keys=True))
