"""Authenticated operator entrypoint for disposable worker lifecycle and smoke."""

from __future__ import annotations

import json
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections, connection
from shifter_adapter_sdk.runtime import decode_message

from engine.services import (
    WorkerView,
    acquire_worker_hold,
    bind_worker_trial,
    configure_worker_policy,
    create_disposable_worker,
    get_disposable_worker,
    list_worker_holds,
    qualify_disposable_worker,
    reconcile_disposable_workers,
    release_worker_hold,
    resume_worker_cleanup,
    retire_disposable_worker,
)
from shared.api_tokens.cli import credential_from_file
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from workspaces.services import hierarchy_target_scope


class Command(BaseCommand):
    """Run authenticated worker operations with bounded, secret-free output."""

    help = "Manage disposable VM workers through the native Engine lifecycle."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the native credential and bounded worker operation inputs."""
        parser.add_argument(
            "action",
            choices=(
                "configure",
                "inspect",
                "retire",
                "hold",
                "release",
                "recover",
                "reconcile",
                "bind-trial",
                "smoke",
            ),
        )
        parser.add_argument("--credential-file", required=True)
        parser.add_argument("--policy-file")
        parser.add_argument("--worker-id", type=UUID)
        parser.add_argument("--hold-id", type=UUID)
        parser.add_argument("--trial-id", type=UUID)
        parser.add_argument("--scope-kind", choices=("account", "organization", "workspace"))
        parser.add_argument("--scope-id", type=UUID)
        parser.add_argument("--reason", choices=("evidence", "capture", "operator"), default="evidence")
        parser.add_argument("--operator-override", action="store_true")
        parser.add_argument("--timeout", type=int, default=900)

    def handle(self, *args: object, **options: object) -> None:
        """Authenticate proof and keep provider or guest errors private."""
        try:
            parsed = Namespace(**options)
            credential = credential_from_file(_required(parsed, "credential_file", str))
            if not 60 <= _required(parsed, "timeout", int) <= 3600:
                raise ValueError("Worker timeout is invalid")
            result = self._dispatch(credential, parsed)
        except Exception:  # noqa: BLE001  # CLI errors must not print proof, provider/guest data, or input bodies
            raise CommandError("Worker command failed; inspect owned worker IDs and recovery state") from None
        self.stdout.write(json.dumps(result, default=str, sort_keys=True))

    def _dispatch(self, credential: CredentialContext, options: Namespace) -> dict[str, object]:
        action = options.action
        if action == "configure":
            with Path(_required(options, "policy_file", str)).open("rb") as handle:
                payload = decode_message(handle.read(131073), limit=131072)
            configure_worker_policy(credential, payload)
            result = {"configured": True}
        elif action == "smoke":
            scope = hierarchy_target_scope(_required(options, "scope_kind", str), _required(options, "scope_id", UUID))
            result = self._smoke(credential, scope, options.timeout)
        elif action == "release":
            result = asdict(
                release_worker_hold(
                    credential, _required(options, "hold_id", UUID), operator_override=options.operator_override
                )
            )
        elif action == "reconcile":
            result = {"processed": reconcile_disposable_workers(credential=credential)}
        else:
            result = self._worker_action(credential, options)
        return result

    def _worker_action(self, credential: CredentialContext, options: Namespace) -> dict[str, object]:
        worker_id = _required(options, "worker_id", UUID)
        if options.action == "inspect":
            result = asdict(get_disposable_worker(credential, worker_id)) | {
                "holds": [asdict(item) for item in list_worker_holds(credential, worker_id)]
            }
        elif options.action == "hold":
            result = asdict(acquire_worker_hold(credential, worker_id, reason=options.reason))
        elif options.action == "bind-trial":
            result = asdict(bind_worker_trial(credential, worker_id, _required(options, "trial_id", UUID)))
        else:
            operation = resume_worker_cleanup if options.action == "recover" else retire_disposable_worker
            result = asdict(operation(credential, worker_id))
        return result

    def _smoke(self, credential: CredentialContext, scope: ResourceScope, timeout: int) -> dict[str, object]:
        """Preallocate both identities so a lost create result cannot lose cleanup custody."""
        identifiers = (uuid4(), uuid4())
        experiment_id = uuid4()
        self.stderr.write(json.dumps({"smoke_worker_ids": [str(value) for value in identifiers]}))
        qualified = []
        cleanup_complete = False
        try:

            def create(identifier: UUID) -> WorkerView:
                close_old_connections()
                try:
                    return create_disposable_worker(
                        credential, scope=scope, worker_id=identifier, experiment_id=experiment_id
                    )
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(create, identifiers))
            self._wait(credential, identifiers, timeout, retiring=False)
            qualified = [qualify_disposable_worker(credential, identifier) for identifier in identifiers]
            for field in ("vm_identity", "machine_identity", "daemon_identity"):
                if len({getattr(item, field) for item in qualified}) != 2:
                    raise ValueError("Worker smoke identities are not independent")
        finally:
            existing = []
            failures = []
            for identifier in identifiers:
                try:
                    get_disposable_worker(credential, identifier)
                    existing.append(identifier)
                    retire_disposable_worker(credential, identifier)
                except ObjectDoesNotExist:
                    continue
                except Exception:  # noqa: BLE001  # the durable worker retains its cleanup obligation
                    failures.append(identifier)
            if existing:
                self._wait(credential, tuple(existing), timeout, retiring=True)
            cleanup_complete = not failures
            if not cleanup_complete:
                raise ValueError("Worker smoke cleanup requires recovery")
        return {
            "worker_ids": [str(value) for value in identifiers],
            "independent_workers": len(qualified),
            "cleanup_verified": cleanup_complete,
        }

    def _wait(
        self, credential: CredentialContext, identifiers: tuple[UUID, ...], timeout: int, *, retiring: bool
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if retiring:
                reconcile_disposable_workers(worker_ids=identifiers)
            workers = [get_disposable_worker(credential, identifier) for identifier in identifiers]
            if all(item.retired if retiring else item.status == "ready" for item in workers):
                return
            if any(
                item.recovery_required or (not retiring and item.status in {"failed", "destroyed", "destroying"})
                for item in workers
            ):
                raise ValueError("Worker smoke requires recovery")
            time.sleep(2)
        raise ValueError("Worker smoke deadline exceeded")


def _required[T](options: Namespace, name: str, expected: type[T]) -> T:
    value = getattr(options, name, None)
    if not isinstance(value, expected):
        raise ValueError("Worker command argument is missing or invalid")
    return value
